import string
import tkinter as tk
import tkinter.messagebox as messagebox
import tkinter.ttk as ttk
import tkinter.font as tkfont
from types import NoneType
from idlelib.tooltip import Hovertip
from typing import Callable, List, Literal, Tuple, cast, get_args

from flexplorer.settings import (
    Cipher,
    Settings,
    LLMSetting,
    LLMProvider,
    LLMReasoningEffort,
    generate_unique_code,
)

__all__ = [
    "SettingsDialog",
]


class _ValidateError(Exception): ...


class _MaskedEntry(ttk.Entry):
    """An Entry widget that masks the input."""

    def __init__(self, master, **kwargs):
        self._store_variable = kwargs.get("textvariable")
        assert isinstance(self._store_variable, (NoneType, tk.StringVar))
        if self._store_variable is None:
            self._store_variable = tk.StringVar()
        self._show_variable = tk.StringVar()
        kwargs["textvariable"] = self._show_variable

        super().__init__(master, **kwargs)

        self._mode: Literal["masked", "plaintext", "nothing"] = "nothing"
        self._store_silent_setting = False
        self._store_variable.trace_add("write", self._on_store_variable_set)
        self._show_silent_setting = False
        self._show_variable.trace_add("write", self._on_input)

        self.bind("<Delete>", self._on_delete)
        self.bind("<BackSpace>", self._on_delete)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)

    @staticmethod
    def masked(value: str) -> str:
        value = value.strip()
        if value == "":
            return ""
        elif len(value) <= 16:
            return "*" * 16
        return f"{value[:8]}{'*' * 23}{value[-4:]}"

    def _store_variable_silent_set(self, value: str):
        """Set the `self._store_variable` variable without triggering the callback."""
        self._store_silent_setting = True
        try:
            assert self._store_variable

            # synchronous triggering: This is not an asynchronous task.
            # the callback executes immediately after set() is called,
            # completing within the same call stack.
            self._store_variable.set(value)
        finally:
            self._store_silent_setting = False

    def _show_variable_silent_set(self, value: str):
        """Set the `self._show_variable` variable without triggering the callback."""
        self._show_silent_setting = True
        try:
            # synchronous triggering: This is not an asynchronous task.
            # the callback executes immediately after set() is called,
            # completing within the same call stack.
            self._show_variable.set(value)
        finally:
            self._show_silent_setting = False

    def _on_store_variable_set(self, *args):
        if self._store_silent_setting:
            return

        assert self._store_variable
        self._show_variable_silent_set(self.masked(self._store_variable.get()))
        self._mode = "masked" if self._store_variable.get() != "" else "nothing"

    def _on_input(self, *args):
        """Triggered when the user types in the Entry widget."""
        if self._show_silent_setting:
            return

        self._store_variable_silent_set(self._show_variable.get())
        if self._mode in ("nothing", "masked"):
            self._mode = "plaintext"

    def _on_delete(self, event: tk.Event):
        self._store_variable_silent_set("")
        self._show_variable_silent_set("")
        self._mode = "nothing"
        return "break"

    def _on_focus_in(self, event: tk.Event):
        self.select_range(0, tk.END)
        self.icursor(tk.END)

    def _on_focus_out(self, event: tk.Event):
        assert self._store_variable is not None
        if self._mode == "plaintext":
            self._show_variable_silent_set(self.masked(self._store_variable.get()))
            self._mode = "masked"


class _LLMSettingForm(ttk.Frame):
    Providers = get_args(LLMProvider)
    ReasoningEffortValues = get_args(LLMReasoningEffort)
    ReasoningEffortLabels = [
        value if value != "none" else "off" for value in ReasoningEffortValues
    ]

    def __init__(
        self,
        master,
        validatecommand: Callable[[LLMSetting]] | None = None,
        confirmcommand: Callable[[], bool] | None = None,
        cancelcommand: Callable[[], bool] | None = None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)

        self._validatecommand = validatecommand
        self._confirmcommand = confirmcommand
        self._cancelcommand = cancelcommand

        # when starting to edit an existing setting,
        # the unique_code of that setting will be saved.
        # if unique_code is empty, it indicates that a new setting is being created.
        self._unique_code = ""

        self._name_var = tk.StringVar()
        self._provider_var = tk.StringVar()
        self._api_key_var = tk.StringVar()
        self._model_var = tk.StringVar()
        self._base_url_var = tk.StringVar()
        self._reasoning_effort_label_var = tk.StringVar()

        self._form_items: List[ttk.Widget] = []

        self.grid(column=0, row=2, sticky=tk.E + tk.SW)
        self.columnconfigure((1, 3), weight=1)
        grid_kwargs = {
            "padx": 5,
            "pady": 2,
            "sticky": tk.EW,
        }
        # name label and entry
        name_label = ttk.Label(self, text="Name :")
        name_label.grid(column=0, row=0, **grid_kwargs)
        name_entry = ttk.Entry(self, textvariable=self._name_var)
        name_entry.grid(column=1, row=0, **grid_kwargs)
        self._form_items.append(name_entry)
        # provider label and combobox
        provider_label = ttk.Label(self, text="Provider :")
        provider_label.grid(column=2, row=0, **grid_kwargs)
        provider_combobox = ttk.Combobox(self, textvariable=self._provider_var)
        provider_combobox.configure(
            values=self.Providers,
        )
        provider_combobox.current(0)
        provider_combobox.grid(column=3, row=0, **grid_kwargs)
        self._form_items.append(provider_combobox)
        # model label and entry
        model_label = ttk.Label(self, text="Model :")
        model_label.grid(column=0, row=1, **grid_kwargs)
        model_entry = ttk.Entry(self, textvariable=self._model_var)
        model_entry.grid(column=1, row=1, **grid_kwargs)
        self._form_items.append(model_entry)
        # reasoning effort label and combobox
        reasoning_effort_label = ttk.Label(self, text="Reasoning Effort :")
        reasoning_effort_label.grid(column=2, row=1, **grid_kwargs)
        reasoning_effort_combobox = ttk.Combobox(
            self,
            textvariable=self._reasoning_effort_label_var,
        )
        reasoning_effort_combobox.grid(column=3, row=1, **grid_kwargs)
        reasoning_effort_combobox.configure(
            # https://developers.openai.com/api/docs/guides/reasoning
            values=self.ReasoningEffortLabels,
        )
        reasoning_effort_combobox.current(0)
        self._form_items.append(reasoning_effort_combobox)
        # base url label and entry
        base_url_label = ttk.Label(self, text="Base URL :")
        base_url_label.grid(column=0, row=2, **grid_kwargs)
        base_url_entry = ttk.Entry(self, textvariable=self._base_url_var)
        base_url_entry.grid(column=1, row=2, columnspan=3, **grid_kwargs)
        self._form_items.append(base_url_entry)
        # api key label and entry
        api_key_label = ttk.Label(self, text="API Key :")
        api_key_label.grid(column=0, row=3, **grid_kwargs)
        api_key_entry = _MaskedEntry(self, textvariable=self._api_key_var)
        api_key_entry.grid(column=1, row=3, columnspan=3, **grid_kwargs)
        self._form_items.append(api_key_entry)

        # bottom buttons
        bottom_frame = ttk.Frame(self)
        bottom_frame.grid(column=0, row=4, columnspan=4)
        bottom_frame.rowconfigure(0, weight=1)
        bottom_frame.columnconfigure((0, 3), weight=1)
        # cancel button
        cancel_btn = ttk.Button(bottom_frame, text="Cancel", command=self._on_cancel)
        cancel_btn.grid(column=1, row=0, padx=5, pady=(5, 0), sticky=tk.E)
        self._form_items.append(cancel_btn)
        # confirm button
        confirm_btn = ttk.Button(bottom_frame, text="Confirm", command=self._on_confirm)
        confirm_btn.grid(column=2, row=0, padx=5, pady=(5, 0), sticky=tk.W)
        self._form_items.append(confirm_btn)

        self._disable()

    @classmethod
    def reasoning_effort_label2value(cls, label: str) -> str:
        assert label in cls.ReasoningEffortLabels
        return cls.ReasoningEffortValues[cls.ReasoningEffortLabels.index(label)]

    @classmethod
    def reasoning_effort_value2label(cls, value: str) -> str:
        assert value in cls.ReasoningEffortValues
        return cls.ReasoningEffortLabels[cls.ReasoningEffortValues.index(value)]

    def export_setting(self) -> LLMSetting:
        name = self._name_var.get().strip()
        provider = self._provider_var.get()
        model = self._model_var.get().strip()
        reasoning_effort_label = self._reasoning_effort_label_var.get()
        base_url = self._base_url_var.get().strip()
        api_key = self._api_key_var.get().strip()

        # validate
        if name == "":
            raise _ValidateError("Please enter a name for the LLM")
        if any(ch in string.whitespace + """[]""" for ch in name):
            raise _ValidateError("Name cannot contain whitespace or brackets")
        if name == "DEFAULT":
            raise _ValidateError("Name cannot be 'DEFAULT'")
        if provider not in self.Providers:
            raise _ValidateError("Please select a provider for the LLM")
        if model == "":
            raise _ValidateError("Please enter a model for the LLM")
        if reasoning_effort_label not in self.ReasoningEffortLabels:
            raise _ValidateError("Please select a reasoning effort for the LLM")
        reasoning_effort_value = self.reasoning_effort_label2value(
            reasoning_effort_label
        )
        if base_url == "":
            raise _ValidateError("Please enter a base URL for the LLM")
        if not (
            base_url.startswith("http://") or base_url.startswith("https://")
        ) or any(True for ch in base_url if ch in string.whitespace):
            raise _ValidateError("Please enter a valid base URL for the LLM")
        if api_key == "":
            raise _ValidateError("Please enter an API key for the LLM")

        if self._unique_code == "":
            # it indicates that a new LLM setting is being created.
            self._unique_code = generate_unique_code()

        llm_setting = LLMSetting(
            unique_code=self._unique_code,
            name=name,
            provider=cast(LLMProvider, provider),
            model=model,
            reasoning_effort=cast(LLMReasoningEffort, reasoning_effort_value),
            base_url=base_url,
            api_key=Cipher(api_key),
        )

        if self._validatecommand is not None:
            # If the validation fails, it will raise a _ValidateError.
            self._validatecommand(llm_setting)

        return llm_setting

    def _on_confirm(self):
        if self._confirmcommand is not None:
            if not self._confirmcommand():
                return

        self._clean()
        self._disable()

    def _on_cancel(self):
        if self._cancelcommand is not None:
            if not self._cancelcommand():
                return

        self._clean()
        self._disable()

    def _clean(self):
        for item in self._form_items:
            if isinstance(item, ttk.Combobox):
                item.current(0)
            elif isinstance(item, ttk.Entry):
                item.delete(0, tk.END)

    def _enable(self):
        for item in self._form_items:
            if isinstance(item, ttk.Combobox):
                item.configure(state="readonly")
            elif isinstance(item, (ttk.Entry, ttk.Button)):
                item.configure(state="normal")

    def _disable(self):
        for item in self._form_items:
            if isinstance(item, (ttk.Entry, ttk.Combobox, ttk.Button)):
                item.configure(state="disabled")

    def enter_idle(self):
        self._clean()
        self._disable()

    def enter_editing(self, llm_setting: LLMSetting | None = None):
        self._enable()

        if llm_setting is None:
            # This indicates that a new LLM setting is being created.
            self._unique_code = ""
            self._clean()
        else:
            self._unique_code = llm_setting.unique_code
            self._name_var.set(llm_setting.name)
            self._provider_var.set(llm_setting.provider)
            self._model_var.set(llm_setting.model)
            self._reasoning_effort_label_var.set(
                self.ReasoningEffortLabels[
                    self.ReasoningEffortValues.index(llm_setting.reasoning_effort)
                ]
            )
            self._base_url_var.set(llm_setting.base_url)
            self._api_key_var.set(llm_setting.api_key)


class _LLMsSettingFrame(ttk.Frame):
    def __init__(self, master, llm_settings: List[LLMSetting], **kwargs):
        super().__init__(master, **kwargs)

        self._llm_settings = llm_settings

        self.columnconfigure(0, weight=1)
        self.rowconfigure((0, 2), weight=0)
        self.rowconfigure(1, weight=1)

        # buttons on top
        top_btns_frame = ttk.Frame(self)
        top_btns_frame.grid(column=0, row=0, sticky=tk.NE + tk.W)
        top_btns_frame.columnconfigure(0, weight=1)
        # style for top buttons
        ttk.Style().configure("Mini.TButton", padding=1, borderwidth=1)
        ttk.Style().configure("Add.Mini.TButton", foreground="green")
        ttk.Style().configure("Copy.Mini.TButton", foreground="blue")
        ttk.Style().configure("Move.Mini.TButton", foreground="yellow")
        ttk.Style().configure("Del.Mini.TButton", foreground="red")
        # add button
        add_btn = ttk.Button(
            top_btns_frame,
            text="➕",
            style="Add.Mini.TButton",
            width=2,
            command=self._on_add,
        )
        Hovertip(add_btn, "Add an LLM", hover_delay=500)
        add_btn.grid(column=1, row=0, sticky=tk.NE, padx=5, pady=5)
        # copy button
        self._copy_as_new_btn = ttk.Button(
            top_btns_frame,
            text="🗐",
            style="Copy.Mini.TButton",
            width=2,
            command=self._on_copy,
        )
        self._copy_as_new_btn.configure(state="disabled")
        Hovertip(self._copy_as_new_btn, "Copy as New", hover_delay=500)
        self._copy_as_new_btn.grid(column=2, row=0, sticky=tk.NE, padx=5, pady=5)
        # up button
        self._move_up_btn = ttk.Button(
            top_btns_frame,
            text="▲",
            style="Move.Mini.TButton",
            width=2,
            command=self._on_move_up,
        )
        self._move_up_btn.configure(state="disabled")
        Hovertip(self._move_up_btn, "Move up", hover_delay=500)
        self._move_up_btn.grid(column=3, row=0, sticky=tk.NE, padx=5, pady=5)
        # down button
        self._move_down_btn = ttk.Button(
            top_btns_frame,
            text="▼",
            style="Move.Mini.TButton",
            width=2,
            command=self._on_move_down,
        )
        self._move_down_btn.configure(state="disabled")
        Hovertip(self._move_down_btn, "Move down", hover_delay=500)
        self._move_down_btn.grid(column=4, row=0, sticky=tk.NE, padx=5, pady=5)
        # delete button
        self._del_btn = ttk.Button(
            top_btns_frame,
            text="➖",
            style="Del.Mini.TButton",
            width=2,
            command=self._on_delete,
        )
        self._del_btn.configure(state="disabled")
        Hovertip(self._del_btn, "Delete the LLM", hover_delay=500)
        self._del_btn.grid(column=5, row=0, sticky=tk.NE, padx=5, pady=5)

        # tree on center
        font_desc = ttk.Style().lookup("Treeview.Heading", "font")
        if font_desc is not None:
            heading_font = tkfont.Font(font=font_desc)
            heading_font.configure(weight="normal")  # not bold
            ttk.Style().configure("Treeview.Heading", font=heading_font)
        # tree
        columns = ("provider", "name", "model", "reasoning_effort")
        tree_frame = ttk.Frame(self)
        tree_frame.grid(column=0, row=1, sticky=tk.NSEW)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self._tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="browse"
        )
        self._tree.heading("provider", text="Provider")
        self._tree.heading("name", text="Name")
        self._tree.heading("model", text="Model")
        self._tree.heading("reasoning_effort", text="Reasoning Effort")
        self._tree.grid(column=0, row=0, sticky=tk.NSEW)
        self._tree.bind("<<TreeviewSelect>>", self._on_select_tree_row)
        tree_scrollbar = ttk.Scrollbar(
            tree_frame, orient=tk.VERTICAL, command=self._tree.yview
        )
        self._tree.configure(yscrollcommand=tree_scrollbar.set)
        tree_scrollbar.grid(column=1, row=0, sticky=tk.NS)

        # form on bottom
        self._form_frame = ttk.LabelFrame(self, text="LLM Setting")
        self._form_frame.grid(
            column=0, row=2, padx=10, pady=(10, 0), sticky=tk.E + tk.SW
        )
        self._form = _LLMSettingForm(
            self._form_frame,
            validatecommand=self._on_form_validate,
            confirmcommand=self._form_confirm_command,
            cancelcommand=self._form_cancel_command,
            padding=10,
        )
        self._form.grid(column=0, row=0, sticky=tk.NSEW)

        self._load_settings()

    def _load_settings(self):
        for llm in self._llm_settings:
            reasoning_effort_label = _LLMSettingForm.reasoning_effort_value2label(
                llm.reasoning_effort
            )
            self._tree.insert(
                "",
                "end",
                values=(llm.provider, llm.name, llm.model, reasoning_effort_label),
            )

    def llm_settings(self) -> List[LLMSetting]:
        return self._llm_settings

    def _selected_item_and_index(self) -> Tuple[str, int]:
        """If no item is selected, returns ("", -1)"""
        items = self._tree.selection()
        assert len(items) in (0, 1), items
        if len(items) == 1:
            item = items[0]
            index = self._tree.index(item)
            return item, index
        return "", -1

    def _on_select_tree_row(self, event: tk.Event):
        item, index = self._selected_item_and_index()
        if item == "":
            # When the program logic executes the deselection of an item,
            # it should simultaneously update the relevant state and clean up the data.
            pass
        else:
            llm_setting = self._llm_settings[index]

            self._form.enter_editing(llm_setting)
            self._form_frame.configure(text=f"Editing {llm_setting.name}")

            self._copy_as_new_btn.config(state="normal")
            self._move_up_btn.config(state="normal" if index != 0 else "disabled")
            self._move_down_btn.config(
                state="normal" if index != len(self._llm_settings) - 1 else "disabled"
            )
            self._del_btn.config(state="normal")

    def _deselect_item(self, item: str):
        assert item != "", item
        self._tree.selection_remove(item)

        self._form.enter_idle()
        self._form_frame.configure(text="LLM Setting")

        self._copy_as_new_btn.config(state="disabled")
        self._move_up_btn.config(state="disabled")
        self._move_down_btn.config(state="disabled")
        self._del_btn.config(state="disabled")

    def _on_add(self):
        item, _ = self._selected_item_and_index()
        if item != "":
            self._deselect_item(item)

        self._form.enter_editing(llm_setting=None)
        self._form_frame.configure(text="Adding")

    def _on_copy(self):
        item, index = self._selected_item_and_index()
        assert item != "", item
        assert index != -1, index
        llm_setting = self._llm_settings[index]

        self._deselect_item(item)

        self._form.enter_editing(llm_setting)
        self._form_frame.configure(text="Copy as New")

    def _on_delete(self):
        item, index = self._selected_item_and_index()
        assert item != "", item
        assert index != -1, index
        self._llm_settings.pop(index)

        self._deselect_item(item)
        self._tree.delete(item)

    def _on_move_up(self):
        """Move the selected item up one position"""
        item, index = self._selected_item_and_index()
        assert index > 0, index
        above_index = index - 1
        # above_item = self._tree.get_children()[above_index]
        self._llm_settings[index], self._llm_settings[index - 1] = (
            self._llm_settings[index - 1],
            self._llm_settings[index],
        )
        self._tree.move(item, "", above_index)
        # self._tree.move(above_item, "", index)

        self._move_up_btn.config(state="normal" if above_index != 0 else "disabled")
        self._move_down_btn.config(
            state="normal" if above_index != len(self._llm_settings) - 1 else "disabled"
        )

    def _on_move_down(self):
        """Move the selected item down one position"""
        item, index = self._selected_item_and_index()
        assert index < len(self._llm_settings) - 1, index
        below_index = index + 1
        # below_item = self._tree.get_children()[below_index]
        self._llm_settings[index], self._llm_settings[index + 1] = (
            self._llm_settings[index + 1],
            self._llm_settings[index],
        )
        self._tree.move(item, "", below_index)
        # self._tree.move(below_item, "", index)

        self._move_up_btn.config(state="normal" if below_index != 0 else "disabled")
        self._move_down_btn.config(
            state="normal" if below_index != len(self._llm_settings) - 1 else "disabled"
        )

    def _on_form_validate(self, llm_setting: LLMSetting):
        _, selected_item_index = self._selected_item_and_index()

        same_name_indexes = [
            idx
            for idx, llm in enumerate(self._llm_settings)
            if llm.name == llm_setting.name
        ]
        if not (same_name_indexes == [] or same_name_indexes == [selected_item_index]):
            raise _ValidateError("An LLM with the same name already exists")

    def _form_confirm_command(self) -> bool:
        """Add or modify an LLM setting"""

        selected_item, selected_item_index = self._selected_item_and_index()

        try:
            llm_setting = self._form.export_setting()
        except _ValidateError as e:
            messagebox.showwarning("Error", str(e), parent=self)
            return False

        if selected_item != "":  # modify
            self._llm_settings[selected_item_index] = llm_setting
            self._tree.item(
                selected_item,
                values=(
                    llm_setting.provider,
                    llm_setting.name,
                    llm_setting.model,
                    _LLMSettingForm.reasoning_effort_value2label(
                        llm_setting.reasoning_effort
                    ),
                ),
            )
            self._deselect_item(selected_item)
        else:  # add
            self._llm_settings.append(llm_setting)
            self._tree.insert(
                "",
                tk.END,
                values=(
                    llm_setting.provider,
                    llm_setting.name,
                    llm_setting.model,
                    _LLMSettingForm.reasoning_effort_value2label(
                        llm_setting.reasoning_effort
                    ),
                ),
            )
            self._form_frame.configure(text="LLM Setting")
        return True

    def _form_cancel_command(self) -> bool:
        item, _ = self._selected_item_and_index()
        if item != "":
            self._deselect_item(item)
        else:  # Adding or Copy as New
            self._form_frame.configure(text="LLM Setting")
        return True


class SettingsDialog(tk.Toplevel):
    def __init__(self, master, settings: Settings):
        super().__init__(master)

        self._settings = settings

        self.title("Settings")
        self.geometry("1400x1000")
        self.configure(padx=30, pady=30)

        self.transient(master)
        self.grab_set()  # make modal
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        notebook = ttk.Notebook(self)
        notebook.grid(column=0, row=0, sticky=tk.NSEW)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        # llms
        self._llms_frame = _LLMsSettingFrame(
            notebook, llm_settings=self._settings.llms.copy()
        )
        notebook.add(self._llms_frame, text="LLMs")

        self._save_btn = ttk.Button(self, text="Save", command=self._on_save)
        self._save_btn.grid(column=0, row=1, sticky=tk.E + tk.S)

    def settings(self) -> Settings:
        return self._settings

    def _on_save(self):
        self._settings.llms = self._llms_frame.llm_settings()
        self.destroy()

    def _on_close(self):
        self.destroy()
