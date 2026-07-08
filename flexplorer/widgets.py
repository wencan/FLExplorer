from dataclasses import dataclass
import tkinter as tk
import tkinter.font as tkfont
from typing import List, Literal, Tuple

__all__ = ["TextList"]


class MeasureText(tk.Text):
    """
    A read-only rich text widget.
    Supports adaptive height adjustment.
    """

    def __init__(self, master, cnf={}, **kwargs):
        super().__init__(master, cnf, **kwargs)
        self.config(state=tk.DISABLED)

        self._width_inmemory: int = 0
        self._display_lines_inmemory: int = 0
        self._pixel_height_inmemory: int = 0

        self.bind("<Configure>", self._on_configure)

    def update_text(self, s: str):
        self.config(state=tk.NORMAL)
        self.delete("1.0", tk.END)
        self.insert("1.0", s)
        self.config(state=tk.DISABLED)

        self._width_inmemory = 0
        self._display_lines_inmemory = 0
        self._pixel_height_inmemory = 0

    def display_lines(self) -> int:
        """
        The function should be called after this widget layout is complete or after `update_idletasks`.
        """
        if not self.winfo_ismapped():
            return 1
        if self.winfo_width() <= 1:
            return 1

        if self.winfo_width() == self._width_inmemory:
            return self._display_lines_inmemory

        display_lines = self.count("1.0", tk.END, "displaylines")
        line_count = display_lines[0] if display_lines else 1
        line_count = max(1, line_count)

        return line_count

    def logical_lines(self) -> int:
        """
        The function should be called after this widget layout is complete or after `update_idletasks`.
        """
        if not self.winfo_ismapped():
            return 1
        if self.winfo_width() <= 1:
            return 1

        lines = self.count("1.0", tk.END, "lines")
        line_count = lines[0] if lines else 1
        line_count = max(1, line_count)

        return line_count

    def pixel_height(self) -> int:
        # restore from memory
        width = self.winfo_width()
        if width == self._width_inmemory:
            return self._pixel_height_inmemory

        font = tkfont.nametofont(self.cget("font"))
        line_height = font.metrics("linespace")

        border = int(self.cget("bd"))

        highlight = int(self.cget("highlightthickness"))

        spacing1 = int(self.cget("spacing1")) if "spacing1" in self.keys() else 0
        spacing2 = int(self.cget("spacing2")) if "spacing2" in self.keys() else 0
        spacing3 = int(self.cget("spacing3")) if "spacing3" in self.keys() else 0

        pady = int(self.cget("pady")) if "pady" in self.keys() else 0

        display_lines = self.display_lines()
        logical_lines = self.logical_lines()
        wrap_lines = max(0, display_lines - logical_lines)

        pixel_height = (
            line_height * display_lines
            + spacing1 * display_lines
            + spacing2 * wrap_lines
            + spacing3
            + border * 2
            + highlight * 2
            + pady * 2
        )

        # save to memory
        self._width_inmemory = width
        self._display_lines_inmemory = display_lines
        self._pixel_height_inmemory = pixel_height

        return pixel_height

    def _adjust_height(self):
        line_count = self.display_lines()
        if int(self.cget("height")) != line_count:
            self.configure(height=line_count)

    def _on_configure(self, event: tk.Event):
        self._adjust_height()


class ScrolledFrame(tk.Frame):
    """
    Virtual List of RichText.
    """

    def __init__(
        self,
        master,
        scroll_fps=60,
        scroll_step_px=30,
        **kwargs,
    ):
        super().__init__(master, **kwargs)

        self._canvas = tk.Canvas(self)
        scrollbar = tk.Scrollbar(self, orient=tk.VERTICAL, command=self._on_scrollbar)
        self._canvas.configure(yscrollcommand=scrollbar.set)
        self._canvas.grid(column=0, row=0, sticky=tk.NSEW)
        scrollbar.grid(column=1, row=0, sticky=tk.N + tk.S + tk.E)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)  # scroll bar

        self._canvas.bind("<Configure>", self._on_configure)
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)

        self._scroll_fps = scroll_fps
        self._scroll_step_px = scroll_step_px  # step size
        self._scrolling_offset: float = 0.0

    def _on_configure(self, event: tk.Event):
        pass

    def scrollregion(self) -> Tuple[int, int, int, int]:
        region = self._canvas.cget("scrollregion")
        parts = region.split()
        assert len(parts) == 4
        x0, y0, x1, y1 = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        assert x0 == 0
        assert y0 == 0
        return x0, y0, x1, y1

    def _scrollregion_and_viewport(
        self,
    ) -> Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int]]:
        xview_perent = self._canvas.xview()
        yview_perent = self._canvas.yview()

        scrollregion = self.scrollregion()
        width = scrollregion[2] - scrollregion[0]
        height = scrollregion[3] - scrollregion[1]

        viewport_x0 = int(xview_perent[0] * width)
        viewport_x1 = int(xview_perent[1] * width)
        viewport_y0 = int(yview_perent[0] * height)
        viewport_y1 = int(yview_perent[1] * height)

        return scrollregion, (viewport_x0, viewport_y0, viewport_x1, viewport_y1)

    def viewport(self) -> Tuple[int, int, int, int]:
        _, viewport = self._scrollregion_and_viewport()
        return viewport

    def _on_scrollbar(self, *args):
        self._canvas.yview(*args)

    def _update_scrollregion(self, height: int):
        bbox = (0, 0, self._canvas.winfo_width(), height)
        self._canvas.configure(scrollregion=bbox)

    def _on_mousewheel(self, event: tk.Event):
        # smooth scroll
        # scroll a little bit at a time until the target is reached.
        scrolling = bool(self._scrolling_offset)
        self._scrolling_offset -= event.delta / 120.0 * self._scroll_step_px
        if not scrolling:
            self.after(int(1000 / self._scroll_fps), self._scroll_step)

        return "break"

    def _scroll_step(self):
        # all parameters have been converted to pixel units,
        # except for the fraction variable.

        step = self._scrolling_offset * 0.25
        if abs(step) < 0.5:
            self._scrolling_offset = 0
            return

        scrollregion, viewport = self._scrollregion_and_viewport()
        _, scrollregion_y0, _, scrollregion_y1 = scrollregion
        scrollregion_height = scrollregion_y1 - scrollregion_y0
        _, viewport_y0, _, viewport_y1 = viewport
        viewport_height = viewport_y1 - viewport_y0
        viewport_y0_next = viewport_y0 + step

        if (
            viewport_y0_next < scrollregion_y0
            or viewport_y0_next > scrollregion_y1 - viewport_height
        ):
            # at the top or at the bottom
            self._scrolling_offset = 0
            return

        fraction = viewport_y0_next / scrollregion_height
        self._canvas.yview_moveto(fraction)

        self._scrolling_offset -= step

        self.after(int(1000 / self._scroll_fps), self._scroll_step)


@dataclass
class CanvasItem:
    text: tk.Text
    wid: int


class TextList(ScrolledFrame):
    """
    Virtual List of tkText.
    """

    def __init__(
        self,
        master,
        text_wrap: Literal["none", "char", "word"] = "word",
        item_pady=4,
        scroll_fps=60,
        scroll_step_px=30,
        **kwargs,
    ):
        super().__init__(
            master, scroll_fps=scroll_fps, scroll_step_px=scroll_step_px, **kwargs
        )

        self._text_wrap: Literal["none", "char", "word"] = text_wrap
        self._item_pady = item_pady

        self._strings: List[str] = []
        self._text_pixel_heights: List[int] = []

        self._draw_items: List[CanvasItem | None] = []
        self._discarded_items: List[CanvasItem] = []
        self._unused_texts: List[tk.Text] = []

        # hidden measure widget
        self._measure_text = MeasureText(self._canvas, wrap=self._text_wrap)
        # text height compute depends on the layout.
        # only the x and y coordinate parameters are known.
        # the width parameter will be updated later.
        self._measure_text.place(x=-10000, y=-10000)

    def _on_configure(self, event: tk.Event):
        # In tk.Text.config(width=..., height=...), the width and height parameters
        # are not measured in pixels, but in text units (character-based units).
        self._measure_text.place(width=event.width)
        # recompute pixel height for all texts
        for idx, s in enumerate(self._strings):
            self._text_pixel_heights[idx] = self.measure_text_pixel_height(s)

        # It will be redraw below, so `itemconfig` is redundant.

        # all items must be recreate.
        for item in self._draw_items:
            if item is not None:
                self._discarded_items.append(item)
        self._draw_items = [None] * len(self._strings)

        # after recompute the height of all texts
        full_height = self._full_height()
        self._update_scrollregion(full_height)

        self._draw()

    def measure_text_pixel_height(self, s: str):
        """
        Use a hidden control to measure the text height.
        This will trigger a layout update.
        """

        self._measure_text.update_text(s)
        self._measure_text.update_idletasks()
        pixel_height = self._measure_text.pixel_height()

        return pixel_height

    def _on_scrollbar(self, *args):
        super()._on_scrollbar(*args)
        self._draw()

    def _scroll_step(self):
        super()._scroll_step()
        self._draw()

    def update_texts(self, strings: List[str]):
        self._strings = strings
        self._text_pixel_heights = [self.measure_text_pixel_height(s) for s in strings]

        for item in self._draw_items:
            if item is not None:
                self._discarded_items.append(item)
        self._draw_items = [None] * len(self._strings)

        full_height = self._full_height()
        self._update_scrollregion(full_height)
        self._draw()

    def _full_height(self):
        total_pady = self._item_pady * 2 * len(self._text_pixel_heights)
        return sum(self._text_pixel_heights) + total_pady

    def _draw(self):
        _, viewport_y0, _, viewport_y1 = self.viewport()

        y0 = 0
        width = self._canvas.winfo_width()
        assert len(self._text_pixel_heights) == len(self._strings)
        assert len(self._draw_items) == len(self._strings)
        for index, s in enumerate(self._strings):
            height = self._text_pixel_heights[index]
            item = self._draw_items[index]
            if y0 + height >= viewport_y0 and y0 <= viewport_y1:  # in viewport
                if item is not None:
                    # move
                    self._canvas.coords(item.wid, 0, y0)
                else:
                    text = self._acquire_unused_item()
                    text.insert(tk.END, s)
                    wid = self._canvas.create_window(
                        0,
                        y0,
                        window=text,
                        anchor=tk.NW,
                        width=width,
                        height=height,
                    )
                    item = CanvasItem(text, wid)
                    self._draw_items[index] = item
            else:  # out of viewport
                if item is not None:
                    self._draw_items[index] = None
                    self._discarded_items.append(item)

            y0 += height + self._item_pady * 2

        for item in self._discarded_items:
            self._canvas.delete(item.wid)
            self._release_unused_item(item.text)
        self._discarded_items = []

    def _release_unused_item(self, text: tk.Text):
        text.delete("1.0", tk.END)
        self._unused_texts.append(text)

    def _acquire_unused_item(self) -> tk.Text:
        if len(self._unused_texts) > 0:
            return self._unused_texts.pop(0)
        else:
            text = tk.Text(self._canvas, wrap=self._text_wrap)
            text.bind("<MouseWheel>", self._on_mousewheel)
            return text
