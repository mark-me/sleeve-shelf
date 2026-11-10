"""Recognising a sleeve on a photo among the covers of the collection.

Each cover is described by its corners and edges (ORB features). The features of a photo look
for their nearest ones among all covers at once; a cover with many clear matches is a candidate.
The best candidates are then checked for the photo showing them as one flat square, seen at an
angle (a homography): matches that fit that shape are what makes a cover recognised. Tried on
photos of Mark's own sleeves, behind the acrylic of a top-loader too (2026-11-08).
"""

from dataclasses import dataclass

import cv2
import numpy as np

# The longest side a cover is described at, and how many features it keeps.
COVER_PIXELS = 400
COVER_FEATURES = 300
# The same for a photo: it holds more than the sleeve, so more of them.
PHOTO_PIXELS = 900
PHOTO_FEATURES = 800
# A match counts when it is clearly nearer than the next best one.
RATIO = 0.75
# How many candidates are checked for their shape, and how many matches that takes.
CHECKED = 15
LEAST_MATCHES = 8
# How far, in pixels, a match may lie from where the shape puts it.
SHAPE_TOLERANCE = 6.0
# Recognised with certainty: this many matches fit the shape, and at least twice as many as
# for the next candidate. On the trial photos every cover with 15 or more was the right one,
# and one with 10 the wrong volume of a series sharing its sleeve.
SURE_FITTING = 15
# A candidate worth showing has matches that fit, or at least this many matches.
LEAST_SHOWN_MATCHES = 2


@dataclass(frozen=True)
class Described:
    """The features of one cover.

    Attributes:
        album_id: The album.
        points: Where each feature lies on the cover, as (x, y).
        descriptors: What each feature looks like, as ORB's 32 bytes.
    """

    album_id: int
    points: np.ndarray
    descriptors: np.ndarray


@dataclass(frozen=True)
class Candidate:
    """A cover the photo may show.

    Attributes:
        album_id: The album.
        fitting: How many matches fit the photo showing the cover as one flat square.
        matches: How many clear matches there were.
    """

    album_id: int
    fitting: int
    matches: int


def _smaller(gray: np.ndarray, pixels: int) -> np.ndarray:
    height, width = gray.shape[:2]
    scale = pixels / max(height, width)
    if scale >= 1:
        return gray
    return cv2.resize(gray, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)


def describe_cover(album_id: int, gray: np.ndarray) -> Described | None:
    """The features of a cover.

    Args:
        album_id: The album.
        gray: The cover in grey, as an array of rows of pixels.

    Returns:
        Its features; None for a cover with too little on it to recognise.
    """
    points, descriptors = cv2.ORB_create(nfeatures=COVER_FEATURES).detectAndCompute(_smaller(gray, COVER_PIXELS), None)
    if descriptors is None or len(points) < LEAST_MATCHES:
        return None
    return Described(album_id, np.float32([point.pt for point in points]), descriptors)


class CoverIndex:
    """All covers, to look a photo up in.

    The nearest features are found by locality-sensitive hashing, which suits ORB's binary
    features. Looking up is safe from one thread at a time; the caller holds a lock.
    """

    def __init__(self, covers: list[Described]):
        """Index the covers.

        Args:
            covers: The features of each cover.
        """
        self.covers = [cover for cover in covers if len(cover.descriptors)]
        # Per feature in the index: which cover, and which of its features.
        self._owner = [(index, k) for index, cover in enumerate(self.covers) for k in range(len(cover.descriptors))]
        self._matcher = cv2.FlannBasedMatcher(
            {"algorithm": 6, "table_number": 4, "key_size": 14, "multi_probe_level": 1}, {"checks": 32}
        )
        if self.covers:
            self._matcher.add([np.vstack([cover.descriptors for cover in self.covers])])
            self._matcher.train()

    def candidates(self, gray: np.ndarray, most: int = 3) -> list[Candidate]:
        """The covers the photo may show, the likeliest first.

        Args:
            gray: The photo in grey.
            most: How many at most.

        Returns:
            The candidates worth showing; none when nothing on the photo looks like a cover.
        """
        if not self.covers:
            return []
        points, descriptors = cv2.ORB_create(nfeatures=PHOTO_FEATURES).detectAndCompute(_smaller(gray, PHOTO_PIXELS), None)
        if descriptors is None or len(points) < 2:
            return []
        where = np.float32([point.pt for point in points])
        found: dict[int, list[tuple[int, int]]] = {}
        for pair in self._matcher.knnMatch(descriptors, k=2):
            if len(pair) == 2 and pair[0].distance < RATIO * pair[1].distance:
                cover, feature = self._owner[pair[0].trainIdx]
                found.setdefault(cover, []).append((feature, pair[0].queryIdx))
        likeliest = sorted(found.items(), key=lambda item: -len(item[1]))[:CHECKED]
        checked = [
            Candidate(self.covers[cover].album_id, _fitting(self.covers[cover], where, pairs), len(pairs))
            for cover, pairs in likeliest
        ]
        checked.sort(key=lambda candidate: (-candidate.fitting, -candidate.matches))
        shown = [c for c in checked if c.fitting or c.matches >= LEAST_SHOWN_MATCHES]
        return shown[:most]


def _fitting(cover: Described, where: np.ndarray, pairs: list[tuple[int, int]]) -> int:
    """How many matches fit the photo showing the cover as one flat square, seen at an angle."""
    if len(pairs) < LEAST_MATCHES:
        return 0
    source = cover.points[[feature for feature, _ in pairs]]
    target = where[[photo_feature for _, photo_feature in pairs]]
    _, mask = cv2.findHomography(source, target, cv2.RANSAC, SHAPE_TOLERANCE)
    return int(mask.sum()) if mask is not None else 0


def is_sure(candidates: list[Candidate]) -> bool:
    """Whether the first candidate is recognised with certainty.

    Args:
        candidates: The candidates, the likeliest first.

    Returns:
        True when enough matches fit, and clearly more than for the next one.
    """
    if not candidates or candidates[0].fitting < SURE_FITTING:
        return False
    return len(candidates) == 1 or candidates[0].fitting >= 2 * candidates[1].fitting
