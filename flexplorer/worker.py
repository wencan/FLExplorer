from flexplorer.formats.epub import Epub
from typing import List, Tuple


class Worker:
    def __init__(self, filepath: str, encoding: str = "utf-8"):
        self._epub = Epub(filepath, encoding)

    def book_title(self) -> str:
        return self._epub.title()

    def book_contents(self) -> List[Tuple[str, str, str]]:
        """
        Returns:
            List[Tuple[str, str, str]]: [(index of parent, index, title), ...]
        """
        return self._epub.chapters()

    def book_chapter(self, index: str) -> List[str]:
        return self._epub.chapter(index)

    def close(self):
        self._epub.close()
