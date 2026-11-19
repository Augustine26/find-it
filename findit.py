"""
FindIt 2.1 - instant file search with a Windows 11 glass look.
Run:  python findit.py            (see README.txt to build FindIt.exe)
This tiny launcher starts first: if FindIt is already running it just hands the request over (instant),
otherwise it loads the full app.
"""
import sys
import argparse


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--path", default=None)
    ap.add_argument("--background", action="store_true")
    ap.add_argument("--elevated", action="store_true")
    ap.add_argument("--new", action="store_true")      # force a separate window
    args, _ = ap.parse_known_args()
    if not args.new:
        import ipc
        if ipc.send({"path": args.path, "background": args.background}):
            return
    import app
    app.run(args)


if __name__ == "__main__":
    main()
