FindIt 2.0 - instant file search for Windows 11

MAKE THE PROGRAM
  1. Install Python from python.org (tick "Add python.exe to PATH")
  2. Double-click build.bat
  3. You get   dist\FindIt\FindIt.exe          (the program, starts fast)
     and, if Inno Setup is installed (jrsoftware.org/isdl.php):
               Output\FindIt-Setup.exe         (the installer)
  No Python? Use .github\workflows\build.yml on GitHub (instructions inside the file).

TRY IT WITHOUT BUILDING
  pip install customtkinter pillow watchdog send2trash pystray pymupdf
  python findit.py

MAKE IT INSTANT (like Everything)
  Settings > Windows > "Run as administrator for instant NTFS indexing".
  FindIt then reads the NTFS file table directly: whole PC in seconds, every start.
  Without it FindIt uses a fast multi-threaded scanner and the saved index.

SEARCH
  report 2026            all words      "annual report"   exact phrase
  jpg|png                either         !draft            leave out
  *.pdf   img_??         wildcards      regex:^IMG_\d+    regular expression
  ext:pdf;docx           extensions     size:>10mb  size:1mb..5mb  size:empty
  dm:today  dm:week  dm:2026-11  dm:>2026-01-01       date modified
  dc:thisweek            date created / added
  folder:  file:  path:projects  type:pictures
  Tools > Search inside files...   looks inside text and Word files of the current results

KEYS
  Ctrl+F search  Ctrl+T new tab  Ctrl+W close tab  Ctrl+N new window  Ctrl+B side panel
  Ctrl+P preview  Ctrl+D bookmark  Ctrl+Shift+D duplicates  Ctrl+, settings  F5 rebuild
  F2 rename  Del recycle bin  Alt+Enter properties  Ctrl+C copy path  Esc clear
  Ctrl+Alt+Space  open FindIt from anywhere (when enabled)

DUPLICATES
  Tools > Find duplicate files. Scans the current results or the whole index (same content or same
  name+size). The newest copy of each file is kept; older copies are marked. Click a row to change
  a mark, then "Delete marked" sends them to the Recycle Bin (never permanent).

NOTES
  Settings, bookmarks, history and the saved index live in %APPDATA%\FindIt
  Windows SmartScreen may warn about a new program: More info > Run anyway.

THUMBNAILS
  Pictures, PDFs, videos, Word/Excel/PowerPoint files, music with album art and more show a real
  picture in the thumbnail views and the preview pane (Windows uses the same thumbnail engine as
  File Explorer; PDFs also work through the built-in PyMuPDF renderer). Files with no picture keep
  a coloured badge with their extension.
