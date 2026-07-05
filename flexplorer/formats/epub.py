import zipfile
import os.path
import posixpath
import xml.etree.ElementTree as ET
import urllib.parse

from typing import Tuple, List


class EpubError(Exception):
    pass


class Epub:
    def __init__(self, filepath: str, encoding: str = "utf-8"):
        self._file = zipfile.ZipFile(filepath)
        self._title = ""
        self._chapters: List[
            Tuple[str, str, str]
        ] = []  # [(index of parent, index, title), ...]

        try:
            self._parse_metadata()
        except:
            self._file.close()
            raise

    def _parse_metadata(self):
        try:
            with self._file.open("META-INF/container.xml") as container_file:
                container_tree = ET.parse(container_file)  # tag: container
                container_root = container_tree.getroot()
                rootfile_ele = container_root.find(
                    "{*}rootfiles/{*}rootfile"
                )  # ignore namespace
                if rootfile_ele is None:
                    raise ET.ParseError("rootfile not found")
                content_opf_path = rootfile_ele.attrib["full-path"]

            content_dir = os.path.dirname(content_opf_path)

            with self._file.open(content_opf_path) as content_file:
                content_tree = ET.parse(content_file)
                content_root = content_tree.getroot()  # tag: package
                metadata_ele = content_root.find("{*}metadata")
                if metadata_ele is None:
                    raise ET.ParseError("metadata not found")
                title_ele = metadata_ele.find("{*}title")
                self._title = title_ele.text or "" if title_ele is not None else ""

                manifest_ele = content_root.find("{*}manifest")
                if manifest_ele is None:
                    raise ET.ParseError("manifest not found")

                # EPUB 2
                ncx_ele = manifest_ele.find(
                    "{*}item[@media-type='application/x-dtbncx+xml']"
                )
                ncx_path = ""
                if ncx_ele is not None:
                    ncx_path = posixpath.join(content_dir, ncx_ele.attrib["href"])

                # EPUB 3
                nav_eles = manifest_ele.findall(
                    "{*}item[@media-type='application/xhtml+xml'][@properties='nav']"
                )
                nav_ele = next(
                    (
                        item
                        for item in nav_eles
                        if "nav" in item.get("properties", "").split()
                    ),
                    None,
                )
                nav_path = ""
                if nav_ele is not None:
                    nav_path = posixpath.join(content_dir, nav_ele.attrib["href"])

                if ncx_path == "" and nav_path == "":
                    raise ET.ParseError("nav not found")

            # contents of EPUB 3
            if nav_path:
                self._parse_chapter_for_epub3(nav_path)
            # contents of EPUB 2
            elif ncx_path:
                self._parse_chapter_for_epub2(ncx_path)
            else:
                raise ET.ParseError("nav not found")

        except ET.ParseError as e:
            raise EpubError("invalid EPUB") from e

    def _parse_chapter_for_epub2(self, ncx_path: str):
        dir_name = os.path.dirname(ncx_path)

        with self._file.open(ncx_path) as ncx_file:
            ncx_tree = ET.parse(ncx_file)
            ncx_root = ncx_tree.getroot()  # tag: ncx
            nav_map_ele = ncx_root.find("{*}navMap")
            if nav_map_ele is None:
                raise ET.ParseError("navMap not found")

            index_set = set()

            def find_childen_for_epub2(parent_ele: ET.Element, parent_index: str = ""):
                nav_point_eles = parent_ele.findall("{*}navPoint")
                for nav_point_ele in nav_point_eles:
                    content_ele = nav_point_ele.find("{*}content")
                    if content_ele is None:
                        raise ET.ParseError("content not found")
                    href = content_ele.attrib["src"]
                    href = urllib.parse.urlunsplit(
                        urllib.parse.urlsplit(href)._replace(fragment="")
                    )  # remove fragment
                    index = os.path.join(dir_name, href)
                    if index in index_set:
                        continue

                    title_ele = nav_point_ele.find("{*}navLabel/{*}text")
                    if title_ele is None:
                        raise ET.ParseError("navLabel not found")
                    title = title_ele.text
                    if title is None or title == "":
                        continue

                    self._chapters.append((parent_index, index, title))
                    index_set.add(index)

                    find_childen_for_epub2(nav_point_ele, index)

            find_childen_for_epub2(nav_map_ele)

    def _parse_chapter_for_epub3(self, nav_path: str):
        dir_name = os.path.dirname(nav_path)

        with self._file.open(nav_path) as nav_file:
            nav_tree = ET.parse(nav_file)
            nav_root = nav_tree.getroot()  # tag: html
            nav_eles = nav_root.findall("{*}body/{*}nav")
            nav_ele = next(
                (
                    ele
                    for ele in nav_eles
                    if any(
                        attr
                        for attr in ele.attrib.items()
                        if attr[0].endswith("type") and attr[1] == "toc"
                    )
                ),
                None,
            )
            if nav_ele is None:
                raise ET.ParseError("nav not found")

            index_set = set()

            def find_childen_for_epub3(parent_ele: ET.Element, parent_index: str = ""):
                ol_ele = parent_ele.find("{*}ol")
                if ol_ele is None:
                    return

                li_eles = ol_ele.findall("{*}li")
                for li_ele in li_eles:
                    a_ele = li_ele.find("{*}a[@href]")
                    if a_ele is None:
                        continue
                    href = a_ele.attrib["href"]
                    href = urllib.parse.urlunsplit(
                        urllib.parse.urlsplit(href)._replace(fragment="")
                    )  # remove fragment
                    index = os.path.join(dir_name, href)
                    if index in index_set:
                        continue

                    title = a_ele.text
                    if title is None or title == "":
                        continue

                    self._chapters.append((parent_index, index, title))
                    index_set.add(index)

                    find_childen_for_epub3(li_ele, index)

            find_childen_for_epub3(nav_ele)

    def title(self) -> str:
        return self._title

    def chapters(self) -> List[Tuple[str, str, str]]:
        """
        Returns:
            List[Tuple[str, str, str]]: [(index of parent, index, title), ...]
        """
        return self._chapters

    def chapter(self, index: str) -> List[str]:
        with self._file.open(index) as html_file:
            html_tree = ET.parse(html_file)
            html_root = html_tree.getroot()

            # remove namespace
            for ele in html_root.iter():
                if "}" in ele.tag:
                    ele.tag = ele.tag.rpartition("}")[-1]
                for attr in list(ele.attrib.keys()):
                    if "}" in attr:
                        ele.attrib[attr.rpartition("}")[-1]] = ele.attrib[attr]

            paragraphs: List[str] = []

            def parse_node(ele: ET.Element):
                parts: List[str] = []
                if ele.text is not None and ele.text != "":
                    parts.append(ele.text)
                for child in ele:
                    parts.append(ET.tostring(child, encoding="unicode", method="html"))

                paragraphs.append("".join(parts))

            def ele_filter(parent_ele: ET.Element, grandfather_tags: List[str] = []):
                for child in parent_ele:
                    # h1, h2, h3, h4, h5, h6, p:not(li p), li, a.hlink[href]:not(p a, li a)
                    # It may occur that a p node is nested under an li node, and an a node may be under either a p node or an li node.
                    # However, this is not a full tree-wide blind search, and it does not recursively search within p and li nodes,
                    # so this behavior can be ignored.
                    if child.tag in [
                        "h1",
                        "h2",
                        "h3",
                        "h4",
                        "h5",
                        "h6",
                        "li",
                    ]:
                        parse_node(child)
                    elif child.tag == "p":
                        parse_node(child)
                    elif child.tag == "a":
                        parse_node(child)
                    else:
                        ele_filter(child, [child.tag] + grandfather_tags)

            ele_filter(html_root)

        return paragraphs

    def close(self):
        self._file.close()
