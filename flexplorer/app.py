import tkinter as tk
import tkinter.ttk as ttk
import tkinter.filedialog as fd
import os.path
import pathlib
import io
from typing import cast, List, Tuple
from flexplorer.worker import Worker

ICON_PATH = os.path.join(os.path.dirname(__file__), "resources", "icons")
OPEN_ICON_PATH = os.path.join(ICON_PATH, "document-open.png")
EXIT_ICON_PATH = os.path.join(ICON_PATH, "application-exit.png")


class App:
    def __init__(self):
        self._root = tk.Tk()
        self._root.title("FLExplorer")

        self._chapters_tree: ttk.Treeview | None = None
        self._chapter_canvas: tk.Canvas | None = None
        self._paragraphs_frame: ttk.Frame | None = None

        self._all_paragraph_texts: List[
            Tuple[ttk.Frame, tk.Text]
        ] = []  # contain hidden widgets
        self._visible_paragraph_num: int = 0
        self._waiting_paragraphs: List[str] = []

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

        # chapter
        self._setup_chapter_ui(body_paned)

        # update
        self._root.update()
        body_paned.sashpos(0, self._root.winfo_width() // 5)

    def _setup_chapter_ui(self, body_paned: ttk.PanedWindow):
        container_frame = ttk.Frame(body_paned)
        body_paned.add(container_frame, weight=1)

        self._chapter_canvas = tk.Canvas(container_frame)
        scroolbar = ttk.Scrollbar(
            container_frame,
            orient=tk.VERTICAL,
            command=self._chapter_canvas.yview,
        )
        self._chapter_canvas.configure(yscrollcommand=scroolbar.set)
        self._chapter_canvas.grid(column=0, row=0, sticky=tk.NSEW)
        scroolbar.grid(column=1, row=0, sticky=tk.NS)
        container_frame.rowconfigure(0, weight=1)
        container_frame.columnconfigure(0, weight=1)

        self._paragraphs_frame = ttk.Frame(self._chapter_canvas)
        self._paragraphs_frame.rowconfigure(0, weight=1)
        self._paragraphs_frame.columnconfigure(0, weight=1)
        paragraphs_frame_wid = self._chapter_canvas.create_window(
            0, 0, window=self._paragraphs_frame, anchor=tk.NW
        )

        canvas = self._chapter_canvas
        # update scroll area
        self._paragraphs_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        # follow width
        self._chapter_canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(paragraphs_frame_wid, width=e.width),
        )
        self._chapter_canvas.bind_all(
            "<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
        )

    def update_paragraphs(self, paragraphs: List[str]):
        for idx, (frame, text) in enumerate(self._all_paragraph_texts):
            if idx < len(paragraphs):
                if idx < self._visible_paragraph_num:
                    text.delete("1.0", tk.END)
                else:
                    frame.grid()
                    self._visible_paragraph_num += 1

                text.insert(tk.END, paragraphs[idx])
                # self._auto_adjust_height_for_text(text)
                self._root.after_idle(self._auto_adjust_height_for_text, text)
            else:
                if idx < self._visible_paragraph_num:
                    frame.grid_remove()
                    text.delete("1.0", tk.END)
                    self._visible_paragraph_num -= 1

        if len(paragraphs) > len(self._all_paragraph_texts):
            self._waiting_paragraphs = paragraphs[len(self._all_paragraph_texts) :]
            self._root.after_idle(self._add_paragraph_text_task)

    def _on_text_mousewheel(self, event: tk.Event):
        assert self._chapter_canvas is not None
        self._chapter_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def _add_paragraph_text(self, paragraph: str = "") -> Tuple[ttk.Frame, tk.Text]:
        assert self._paragraphs_frame is not None
        frame = ttk.Frame(self._paragraphs_frame)
        frame.grid(
            column=0, row=len(self._all_paragraph_texts), sticky=tk.NSEW, padx=5, pady=5
        )
        frame.columnconfigure(0, weight=1)

        text = tk.Text(frame, height=1, wrap=tk.WORD)
        text.insert(tk.END, paragraph)
        # text.configure(state=tk.DISABLED)
        text.grid(column=0, row=0, sticky=tk.NSEW)

        text.bind("<MouseWheel>", self._on_text_mousewheel)

        # self._auto_adjust_height_for_text(text)
        self._root.after_idle(self._auto_adjust_height_for_text, text)

        self._all_paragraph_texts.append((frame, text))
        self._visible_paragraph_num += 1

        return frame, text

    def _auto_adjust_height_for_text(self, text: tk.Text):
        text.update_idletasks()
        display_lines = text.count("1.0", tk.END, "displaylines")
        line_count = display_lines[0] if display_lines else 1
        line_count = max(1, line_count)
        text.configure(height=line_count)

    def _add_paragraph_text_task(self):
        if len(self._waiting_paragraphs) == 0:
            return

        paragraph = self._waiting_paragraphs.pop(0)
        self._add_paragraph_text(paragraph)

        if len(self._waiting_paragraphs) > 0:
            self._root.after_idle(self._add_paragraph_text_task)

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

        self._cleanup_chapter()

        assert self._chapters_tree is not None
        self._chapters_tree.delete(*self._chapters_tree.get_children())

        self._current_content_index = ""

    def _cleanup_chapter(self):
        for idx in range(self._visible_paragraph_num):
            frame, _ = self._all_paragraph_texts[idx]
            frame.grid_remove()
        self._visible_paragraph_num = 0
        self._waiting_paragraphs = []

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
        assert len(indexes) == 1
        self._selected_chapter_index = indexes[0]

        assert self._worker is not None
        paragraphs = self._worker.book_chapter(self._selected_chapter_index)
        self.update_paragraphs(paragraphs)

    def _on_exit(self, *args):
        self._root.destroy()

    def run(self):
        self._setup_ui()
        self._root.mainloop()
