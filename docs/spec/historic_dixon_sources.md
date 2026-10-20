# Historic Dixon Sources

Research notes for building a dated, historic version of the Dixon model. Captured 2026-10-20 while on the road via voice. All Sanborn material predating 1923 is public domain and free to download.

## Sanborn Fire Insurance Maps (primary source for building footprints, materials, use)

- **Dixon, Lee County, IL — August 1897** (15 sheets). Library of Congress. Public domain, TIFF download available.
  - Slideshow: https://www.loc.gov/resource/g4104dm.g018271897/?st=slideshow
  - Handle: http://hdl.loc.gov/loc.gmd/g018271897
  - Digital ID: g4104dm.g018271897
- **Dixon, Illinois — July 1885** (5 pages). University of Illinois Urbana-Champaign Digital Collections. Pre-1923, free.
  - Collection: Sanborn Fire Insurance Maps — https://digital.library.illinois.edu/collections/6ff64b00-072d-0130-c5bb-0019b9e633c5-2
  - Item search: search "Dixon" in that collection; the 1885 entry is titled "Dixon, Illinois, July 1885".
- **Dixon, Lee County, Illinois — August 1926** (28 pages). UIUC Digital Collections. Post-1923, may have copyright restrictions — verify before reuse.
  - Same collection as above; search "Dixon" for the 1926 entry.
- **Amboy, Lee County, IL — 1885, 1892, 1897, 1902, 1910, 1918, 1931, 1943** (neighboring town, useful for regional context). UIUC + Southern Illinois University Carbondale. See the Union List of Sanborn Maps for Illinois.
  - Union List: https://digitalassets.lib.berkeley.edu/sanborn/sanbul_IL_A.html

## Other map sources

- **Warner & Beers / Union Atlas Co., 1876** — Map of Rock Island County with Dixon inset (wards, landowners, railroads, schools, churches, farmhouses). David Rumsey Historical Map Collection.
  - https://davidrumsey.com/maps3747.html (List No. 1159.022)
- **Pastmaps — Old Maps of Dixon, IL**: 26 historic maps spanning 1918 to today, sourced from USGS, Library of Congress, National Library of Scotland. High-res downloads and satellite/LiDAR overlay.
  - https://pastmaps.com/explore/us/illinois/lee-county/dixon-township/dixon
- **USGS Historical Map GeoPDF — Dixon, IL, 1:62,500, 1918** ($15 from USGS Store, product 858618). Also a 1950 version.
  - https://store.usgs.gov/product/858618
- **USGS Historical Map GeoPDF — Dixon, IL, 1:62,500, 1950** (same product page).
- **Illinois State Archives — Federal Township Plats of Illinois (1804–1891)**: 3,457 hand-drawn plats, free online. Useful for pre-settlement and early-settlement landscape before urban detail existed.
  - Search "Federal Township Plats" on the Illinois State Archives site.
- **Newberry Library — Diagram of the State of Illinois, 1850**: shows Dixon County and early towns. Free, no licensing fee.
  - https://collections.carli.illinois.edu/digital/collection/nby_chicago/id/1414/
- **Historical Illinois Maps — Vintage Gazetteers** (Century Past): free online collection of Illinois atlases, gazetteers, and historical maps.
  - https://centurypast.org/great-lakes-states/illinois-maps-gazettes/
- **USGenWeb Archives Digital Map Library — Illinois**: free contributed scans including county plat maps (e.g., 1870 Boone County, Clark County ca. 1930).
  - http://usgwarchives.net/maps/illinois/

## Bulk / machine-readable access

- **Library of Congress Sanborn Maps Data Package** (LC Labs, experimental): metadata for 50,600 maps and 440,048 images in CSV and JSON. Good candidate to feed dated building records into the canon layer.
  - https://data.labs.loc.gov/sanborn/
- **LOC Sanborn searching guide**: https://guides.loc.gov/fire-insurance-maps/sanborn-searching
- **LOC Sanborn downloading guide** (includes bulk-access notes and Jupyter notebooks): https://guides.loc.gov/fire-insurance-maps/sanborn-downloading
- **CARLI Digital Collections — Sanborn Maps of Illinois, 1867–1970**: browse/search by city or county; high-res TIFF downloadable from each item's metadata. Off-campus access may require university affiliation.
  - https://collections.carli.illinois.edu/digital/collection/sanborn
- **BTAA Geoportal — Digital Sanborn Maps (Black & White) Illinois 1867–1970**: includes Dixon; restricted/subscription access.
  - https://geo.btaa.org/catalog/999-0011-illinois
- **ProQuest Digital Sanborn Maps 1867–1970**: commercial database, 660,000+ maps of 12,000+ towns. Check local library access.

## Notes for the spec layer

- Sanborn maps are drawn at 50 feet to the inch — far more precise for individual structures than any DEM or aerial.
- They record building outline, size, shape, height, construction material (via shading), use (residential/commercial/industrial), addresses, street widths, sidewalks, property boundaries, fire hydrants, and windows/doors on some sheets.
- A dated canon entry can carry from-year / to-year fields so any renderer can slice the world by era.
- The 1885 and 1897 Dixon sets are the best starting points for an 1800s game world; the 1926 set extends coverage into the early auto era.
- Pre-Sanborn coverage (before ~1885) will rely on atlas plates like the 1876 Warner & Beers and township plats — coarser, but enough for roads, rail, and major landmarks.
