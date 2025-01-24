# audiobook_chapter_merger
Script to merge chapter fragments (like those ripped from a CD). Listening to several dozen 5-minute files is annoying and an anachronism of the past. Behold, a script to create individual chapters based on matching a pattern like the below. 

Note: This script will not match "01 Opening Titles.mp3", "02 Prologue A.mp3", or "03 Prologue B.mp3". It keys on the word "Chapter", although the regex can be adjusted to match for your application.
```
WorkingDir
    ├── [Disc 1]
    │   ├── 01 Opening Titles.mp3
    │   ├── 02 Prologue A.mp3
    │   ├── 03 Prologue B.mp3
    │   ├── 04 Chapter 1a.mp3
    │   ├── 05 Chapter 1b.mp3
    │   ├── 06 Chapter 1c.mp3
    │   ├── 07 Chapter 1d.mp3
    │   ├── 08 Chapter 1e.mp3
    │   ├── 09 Chapter 2a.mp3
    │   ├── 10 Chapter 2b.mp3
    │   ├── 11 Chapter 2c.mp3
    │   ├── 12 Chapter 2d.mp3
    │   ├── 13 Chapter 2e.mp3
    │   └── 14 Chapter 2f.mp3
    ├── [Disc 2]
    │   ├── 01 Chapter 2g.mp3
    │   ├── 02 Chapter 2h.mp3
    │   ├── 03 Chapter 3a.mp3
    │   ├── 04 Chapter 3b.mp3
    │   ├── 05 Chapter 3c.mp3
    │   ├── 06 Chapter 3d.mp3
    │   ├── 07 Chapter 3e.mp3
    │   ├── 08 Chapter 3f.mp3
    │   ├── 09 Chapter 4a.mp3
    │   ├── 10 Chapter 4b.mp3
    │   ├── 11 Chapter 4c.mp3
    │   ├── 12 Chapter 4d.mp3
    │   └── 13 Chapter 4e.mp3
```
