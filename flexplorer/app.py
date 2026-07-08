import tkinter as tk
import tkinter.ttk as ttk
import tkinter.filedialog as fd
import os.path
import pathlib
import io
from typing import Any, cast, List
from flexplorer.worker import Worker
from flexplorer.widgets import TextList

ICON_PATH = os.path.join(os.path.dirname(__file__), "resources", "icons")
OPEN_ICON_PATH = os.path.join(ICON_PATH, "document-open.png")
EXIT_ICON_PATH = os.path.join(ICON_PATH, "application-exit.png")


STYLE_MAIN_BG = "white"
STYLE_MAIN_FG = "#2D2D2D"


class App:
    def __init__(self):
        self._root = tk.Tk()
        self._root.title("FLExplorer")

        self._chapters_tree: ttk.Treeview | None = None
        self._main_text: TextList | None = None
        self._selected_chapter_index: str = ""
        self._worker: Worker | None = None

        self._icons: List[tk.Image] = []

    def _setup_ui(self):
        # ------ main windows ------
        w = self._root.winfo_screenwidth()
        h = self._root.winfo_screenheight()
        self._root.geometry(f"{w}x{h}+0+0")  # max window
        self._root.rowconfigure(0, weight=1)
        self._root.columnconfigure(0, weight=1)

        main_frame = ttk.Frame(self._root)
        main_frame.grid(column=0, row=0, sticky=tk.NSEW)
        main_frame.columnconfigure(0, weight=1)

        # ------ ToolBar ------
        toolbar_frame = ttk.Frame(main_frame)
        toolbar_frame.grid(column=0, row=0, sticky=tk.NSEW)
        main_frame.rowconfigure(0, weight=0)

        open_icon = tk.PhotoImage(file=OPEN_ICON_PATH)
        self._icons.append(open_icon)
        open_btn = ttk.Button(
            toolbar_frame,
            text=" Open",
            image=open_icon,
            compound=tk.LEFT,
            command=self._on_open_file,
        )
        open_btn.grid(column=0, row=0, sticky=tk.W)

        exit_icon = tk.PhotoImage(file=EXIT_ICON_PATH)
        self._icons.append(exit_icon)
        exit_btn = ttk.Button(
            toolbar_frame,
            text=" Exit",
            image=exit_icon,
            compound=tk.LEFT,
            command=self._on_exit,
        )
        exit_btn.grid(column=1, row=0, sticky=tk.W)

        # ------ Body ------
        body_paned = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        body_paned.grid(column=0, row=1, sticky=tk.NSEW)
        main_frame.rowconfigure(1, weight=1)

        # chapter tree
        chapter_tree_frame = ttk.Frame(body_paned)
        self._chapters_tree = ttk.Treeview(chapter_tree_frame, selectmode="browse")
        chapter_tree_scroolbar = ttk.Scrollbar(
            chapter_tree_frame, orient=tk.VERTICAL, command=self._chapters_tree.yview
        )
        self._chapters_tree.configure(yscrollcommand=chapter_tree_scroolbar.set)
        self._chapters_tree.grid(column=0, row=0, sticky=tk.NSEW)
        chapter_tree_scroolbar.grid(column=1, row=0, sticky=tk.NSEW)
        chapter_tree_frame.rowconfigure(0, weight=1)
        chapter_tree_frame.columnconfigure(0, weight=1)
        body_paned.add(chapter_tree_frame, weight=1)

        self._chapters_tree.bind("<<TreeviewSelect>>", self._on_select_chapter)

        # main text
        text_style_options = {
            "background": STYLE_MAIN_BG,  # alias: bg
            "foreground": STYLE_MAIN_FG,  # alias: fg
            "borderwidth": 0,  # alias: bd
            "highlightthickness": 0,
        }
        kwargs: dict[str, Any] = {
            "background": STYLE_MAIN_BG,
        }
        self._main_text = TextList(
            body_paned, text_style_options=text_style_options, **kwargs
        )
        body_paned.add(self._main_text, weight=1)

        # update
        self._root.update()
        body_paned.sashpos(0, self._root.winfo_width() // 5)

    def _on_open_file(self, *args):
        file = fd.askopenfile(
            defaultextension=".epub",
            filetypes=[("Epub", "*.epub")],
            initialdir=pathlib.Path.home(),
        )
        if file:
            file = cast(io.TextIOWrapper, file)
            self._open_new_file(file.name, file.encoding)

    def _cleanup(self):
        if self._worker is not None:
            self._worker.close()
            self._worker = None

        assert self._chapters_tree is not None
        self._chapters_tree.delete(*self._chapters_tree.get_children())

        assert self._main_text is not None
        self._main_text.update_texts([])

    def _open_new_file(self, filepath: str, encoding: str = "utf-8"):
        self._cleanup()

        self._worker = Worker(filepath, encoding)

        # update contents
        assert self._chapters_tree is not None
        for parent_index, index, title in self._worker.book_contents():
            self._chapters_tree.insert(parent_index, "end", index, text=title)

        # update title
        self._root.title(f"FLExplorer - {self._worker.book_title()}")

    def _on_select_chapter(self, *args):
        assert self._chapters_tree is not None
        indexes = self._chapters_tree.selection()
        if len(indexes) == 0:  # the chapter tree has been updated.
            return

        assert len(indexes) == 1
        self._selected_chapter_index = indexes[0]

        assert self._worker is not None
        paragraphs = self._worker.book_chapter(self._selected_chapter_index)
        assert self._main_text is not None
        self._main_text.update_texts(paragraphs)

    def _on_exit(self, *args):
        self._root.destroy()

    def run(self):
        self._setup_ui()
        self._root.mainloop()
