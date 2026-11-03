# Albums and artists

Every album and every artist has a page of its own, with what it is, what your collection says about it, and — for you as the owner — what can be changed.

## 💿 An album's page

Open an album by its title, wherever one is listed: a search result, a shelf, its artist's page, Layout, Connections, Statistics and the lists under Discogs and in a sorting proposal. The page has three tabs: **Album**, **Statistics** and — for you as owner — **Manage**.

Under the title, on every tab, stands where the album is: a button to its shelf, with the album marked. Beside it the **▶** button plays its previews. Below that are the albums before and after it along the shelves; the arrow keys or a swipe go there too.

**Album** shows:

- what it is sorted under (cluster and era band)
- its original release year — from Discogs, or confirmed by you
- its Discogs styles, and under **More details** its format and Discogs release
- its **tracklist**: the songs with their place on the record and their length
- **the same songs elsewhere**: the other albums in your collection with one of its songs, and where each stands — another version to pull from the shelf
- **Connections**, beside the artist's name: the artist in the middle of its [connections](connections.md#connections); next to it **Discogs** opens the release on Discogs (an artist's page has the same link to the artist)

**Statistics** shows what your collection says about the album: how many songs and minutes it has, its place among the artist's albums by year with those before and after it, who is on it and on how many of your albums, other albums with several of the same people, who wrote the songs, how many of your albums share its styles and label, and what else you have from its year.

**Manage** holds what can be changed: the suggested spot of an album without a place, its width, a cover of your own, the location rules that apply to it, and a way to put it on another shelf. The first tab says so when an album waits for a place.

### Listen

Under **Listen** you hear what an album sounds like before you pull it from the shelf. The app looks the album up at [Deezer](https://www.deezer.com/) by its artist and title, and plays a **30-second preview** of each track. The cover and title of what was found are shown, so you can see whether it is your album; if it is another one, **Not this album** leaves it out for good.

Below that are the **videos** Discogs users linked to your release — often whole tracks on YouTube. A video is only loaded when you press play.

Listening needs an internet connection; about three in four albums are found at Deezer, less often old compilations and rare pressings.

## 🎤 An artist's page

An artist's page opens on **Artist**: the artist's albums and where each one stands, the artists Discogs connects it to, and what your collection says about it:

- how many albums, its place in your collection, and how many centimetres of shelf they take
- its **styles**: from three albums a bar per Discogs style, otherwise labels. An album can have several styles, so the bars add up to more than the albums
- **through the years**: its albums per year, so gaps show
- **recurring on the records**: who is credited on several of its albums
- **also on**: albums of others it is credited on

**Connections**, under its name, shows the artist in the middle of its [connections](connections.md#connections).

**Manage**, the second tab, holds what can be changed: **start year** (which sets the era band — with a link to look it up), **cluster**, location rules, moving all its albums to another shelf at once, and your own picture of the artist, which is kept with your data and never replaced by a sync. When the artist still needs something from you for the sorting, the first tab says so, and the Artists list takes you straight to Manage. Visitors see only the first part, without tabs.

!!! tip "When the browser can't upload"
    Some managed computers block file uploads in the browser. Add a picture of an artist, or a cover of an album — by the number in its page's address, `/albums/43` — from the command line instead:

    ```sh
    uv run python -m sleeve_shelf set-picture "Miles Davis" path/to/picture.jpg
    uv run python -m sleeve_shelf set-cover 43 path/to/cover.jpg
    ```

On a wide screen the albums are on the left and the figures on the right; on a phone the figures come first.
