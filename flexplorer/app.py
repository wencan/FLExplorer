import asyncio
import threading
import concurrent.futures
import tkinter as tk
import tkinter.ttk as ttk
import tkinter.filedialog as fd
import os.path
import pathlib
import io
from typing import Any, AsyncGenerator, Callable, cast, List, Coroutine
from flexplorer.llm import translate
from flexplorer.formatter import Formatter
from flexplorer.settings import (
    APP_NAME,
    SYS_NAME,
    Settings,
    load_settings,
    save_settings,
)
from flexplorer.widgets import SettingsDialog

ICON_PATH = os.path.join(os.path.dirname(__file__), "resources", "icons")
OPEN_ICON_PATH = os.path.join(ICON_PATH, "document-open.png")
EXIT_ICON_PATH = os.path.join(ICON_PATH, "application-exit.png")
SETTINGS_ICON_PATH = os.path.join(ICON_PATH, "preferences-system.png")


try:
    anext  # type: ignore
except NameError:
    # For Python versions < 3.10, define anext
    async def anext(agen, default=None):
        try:
            return await agen.__anext__()
        except StopAsyncIteration:
            if default is not None:
                return default
            raise


class AsyncLoop:
    def __init__(self, tk: tk.Tk):
        self._root = tk
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None

    def start_asyncio_loop(self):
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._loop.run_forever)
        self._loop_thread.start()

    def stop_asyncio_loop(self):
        assert self._loop is not None
        assert self._loop_thread is not None

        # Tell the asyncio thread: "Please call stop() yourself."
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._loop_thread.join()
        self._loop.close()

        self._loop = None
        self._loop_thread = None

    def call_asyncio_coroutine(
        self,
        coroutine: Coroutine,
        callback: Callable[[Any | None, Exception | None], None],
    ):
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        self._root.after(10, self._on_wait_future, future, callback)

    def _on_wait_future(
        self,
        future: concurrent.futures.Future,
        callback: Callable[[Any | None, Exception | None], None],
    ):
        if future.done():
            try:
                r = future.result()
                callback(r, None)
            except Exception as e:
                callback(None, e)
        else:
            self._root.after(10, self._on_wait_future, future, callback)

    def call_asyncio_generator(
        self,
        generator: AsyncGenerator,
        callback: Callable[[str | None, Exception | None], None],
    ):
        assert self._loop is not None

        afuture = asyncio.run_coroutine_threadsafe(anext(generator), self._loop)
        self._root.after(10, self._on_wait_afuture, afuture, generator, callback)

    def _on_wait_afuture(
        self,
        afuture: concurrent.futures.Future,
        generator: AsyncGenerator,
        callback: Callable[[Any | None, Exception | None], None],
    ):
        assert self._loop is not None

        if afuture.done():
            try:
                r = afuture.result()
                callback(r, None)
            except StopAsyncIteration as e:
                callback(None, e)
            except Exception as e:
                callback(None, e)
            else:
                afuture = asyncio.run_coroutine_threadsafe(anext(generator), self._loop)
                self._root.after(
                    10, self._on_wait_afuture, afuture, generator, callback
                )
        else:
            self._root.after(10, self._on_wait_afuture, afuture, generator, callback)


class App:
    def __init__(self):
        self._root = tk.Tk()
        self._root.title(APP_NAME)

        self._asyn_loop = AsyncLoop(self._root)

        self._settings: Settings | None = None
        self._chapters_tree: ttk.Treeview | None = None
        self._main_text: tk.Text | None = None

        self._selected_chapter_index: str = ""
        self._formatter: Formatter | None = None
        self._cursor_paragraph_index: int | None = None

        self._icons: List[tk.Image] = []

    def _setup_ui(self):
        # ------ main windows ------
        if SYS_NAME == "Windows":
            self._root.state("zoomed")
        elif SYS_NAME == "Linux":
            self._root.attributes("-zoomed", True)
        else:  # mac and others
            w = self._root.winfo_screenwidth()
            h = self._root.winfo_screenheight()
            self._root.geometry(f"{w}x{h}+0+0")
        self._root.rowconfigure(0, weight=1)
        self._root.columnconfigure(0, weight=1)

        root_frame = ttk.Frame(self._root)
        root_frame.grid(column=0, row=0, sticky=tk.NSEW)
        root_frame.columnconfigure(0, weight=1)

        # ------ ToolBar ------
        toolbar_frame = ttk.Frame(root_frame)
        toolbar_frame.grid(column=0, row=0, sticky=tk.NSEW)
        root_frame.rowconfigure(0, weight=0)
        # open file
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
        # settings
        settings_icon = tk.PhotoImage(file=SETTINGS_ICON_PATH)
        self._icons.append(settings_icon)
        settings_btn = ttk.Button(
            toolbar_frame,
            text=" Settings",
            image=settings_icon,
            compound=tk.LEFT,
            command=self._on_open_settings,
        )
        settings_btn.grid(column=1, row=0, sticky=tk.W)
        # exit
        exit_icon = tk.PhotoImage(file=EXIT_ICON_PATH)
        self._icons.append(exit_icon)
        exit_btn = ttk.Button(
            toolbar_frame,
            text=" Exit",
            image=exit_icon,
            compound=tk.LEFT,
            command=self._on_exit,
        )
        exit_btn.grid(column=2, row=0, sticky=tk.W)

        # ------ Body ------
        body_paned = ttk.PanedWindow(root_frame, orient=tk.HORIZONTAL)
        body_paned.grid(column=0, row=1, sticky=tk.NSEW)
        root_frame.rowconfigure(1, weight=1)

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
        body_paned.add(chapter_tree_frame, weight=0)
        self._chapters_tree.bind("<<TreeviewSelect>>", self._on_select_chapter)

        # content
        content_frame = ttk.Frame(body_paned)
        body_paned.add(content_frame, weight=1)

        self._main_text = tk.Text(content_frame)
        self._main_text.grid(column=0, row=0, sticky=tk.NSEW)
        content_frame.columnconfigure(0, weight=1)
        content_vsrollbar = ttk.Scrollbar(
            content_frame, orient=tk.VERTICAL, command=self._main_text.yview
        )
        self._main_text.configure(yscrollcommand=content_vsrollbar.set)
        content_vsrollbar.grid(column=1, row=0, sticky=tk.N + tk.S + tk.E)
        content_frame.rowconfigure(0, weight=1)
        content_frame.columnconfigure(1, weight=0)
        self._main_text.bind("<Motion>", self._on_text_motion)
        self._main_text.configure(state=tk.DISABLED)

        # A child widget can capture the <KeyRelease> event only when it has focus.
        self._root.bind("<KeyRelease>", self._on_key_release)

        # update
        self._root.update()
        body_paned.sashpos(0, self._root.winfo_width() // 5)

    def _on_open_file(self, *args):
        assert self._settings is not None
        initialdir = self._settings.recent.open_file_dirpath
        if initialdir == "":
            initialdir = str(pathlib.Path.home())

        file = fd.askopenfile(
            defaultextension=".epub",
            filetypes=[("Epub", "*.epub")],
            initialdir=initialdir,
        )
        if file:
            file = cast(io.TextIOWrapper, file)
            self._open_new_file(file.name, file.encoding)

            self._settings.recent.open_file_dirpath = os.path.dirname(file.name)
            save_settings(self._settings)

    def _cleanup(self):
        if self._formatter is not None:
            self._formatter.close()
            self._formatter = None

        assert self._chapters_tree is not None
        self._chapters_tree.delete(*self._chapters_tree.get_children())

        assert self._main_text is not None
        self._main_text.configure(state=tk.NORMAL)
        self._main_text.delete("1.0", tk.END)
        self._main_text.configure(state=tk.DISABLED)

        self._selected_chapter_index = ""

    def _translate_paragraph(self, paragraph_index: int, llm_index: int):
        assert self._main_text is not None
        ranges = self._main_text.tag_ranges(f"paragraph_{paragraph_index}")
        assert len(ranges) in (0, 2)
        if len(ranges) == 2:
            start, end = ranges
            text = self._main_text.get(start, end)

            assert self._settings is not None
            assert llm_index < len(self._settings.llms)
            llm_setting = self._settings.llms[llm_index]

            generator = translate(
                provider=llm_setting.provider,
                base_url=llm_setting.base_url,
                api_key=llm_setting.api_key,
                model=llm_setting.model,
                reasoning_effort=llm_setting.reasoning_effort,
                stream=False,
                src=text,
                target_lang="简体中文",
            )

            def callback(result: Any, e: Exception | None):
                if isinstance(e, StopAsyncIteration):
                    print("", flush=True)
                    return
                elif e is not None:
                    print(f"Error: {e}")
                else:
                    translated_text = cast(str, result)
                    print(translated_text, end="", flush=True)

            self._asyn_loop.call_asyncio_generator(generator, callback)

    def _open_new_file(self, filepath: str, encoding: str = "utf-8"):
        self._cleanup()

        self._formatter = Formatter(filepath, encoding)

        # update contents
        assert self._chapters_tree is not None
        for parent_index, index, title in self._formatter.book_contents():
            self._chapters_tree.insert(parent_index, "end", index, text=title)

        # update title
        self._root.title(f"{APP_NAME} - {self._formatter.book_title()}")

    def _on_select_chapter(self, *args):
        assert self._chapters_tree is not None
        indexes = self._chapters_tree.selection()
        if len(indexes) == 0:  # the chapter tree has been updated.
            return

        assert len(indexes) == 1
        self._selected_chapter_index = indexes[0]

        assert self._formatter is not None
        paragraphs = self._formatter.book_chapter(self._selected_chapter_index)

        assert self._main_text is not None
        self._main_text.configure(state=tk.NORMAL)
        self._main_text.delete("1.0", tk.END)
        for idx, paragraph in enumerate(paragraphs):
            start = self._main_text.index("end-1c")
            self._main_text.insert("end-1c", paragraph.strip())
            end = self._main_text.index("end-1c")
            self._main_text.tag_add(f"paragraph_{idx}", start, end)
            if idx != len(paragraphs) - 1:
                self._main_text.insert("end-1c", "\n")
        self._main_text.configure(state=tk.DISABLED)

    def _on_text_motion(self, event: tk.Event):
        assert self._main_text is not None
        index = self._main_text.index(f"@{event.x},{event.y}")
        tags = self._main_text.tag_names(index)
        if tags:
            for tag in tags:
                if tag.startswith("paragraph_"):
                    self._cursor_paragraph_index = int(tag[10:])
                    return

        self._cursor_paragraph_index = None

    def _on_key_release(self, event: tk.Event):
        if isinstance(event.state, int) and (event.state & 0x0004):
            # ctrl key is pressed
            if len(event.keysym) == 1 and event.keysym.isdigit():
                key_num = int(event.keysym)
                assert 0 <= key_num <= 9
                llm_index = key_num - 1 if key_num != 0 else 10
                assert self._settings is not None
                if llm_index < len(self._settings.llms):
                    if self._cursor_paragraph_index is not None:
                        self._translate_paragraph(
                            self._cursor_paragraph_index, llm_index
                        )

    def _on_open_settings(self, *args):
        assert self._settings is not None

        settings_dialog = SettingsDialog(self._root, self._settings)
        self._root.wait_window(settings_dialog)

        self._settings = settings_dialog.settings()
        save_settings(self._settings)

    def _on_exit(self, *args):
        self._root.destroy()

    def _load_settings(self):
        self._settings = load_settings()

    def run(self):
        self._setup_ui()
        self._load_settings()
        self._asyn_loop.start_asyncio_loop()
        self._root.mainloop()
        self._asyn_loop.stop_asyncio_loop()
