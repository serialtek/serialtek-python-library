# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html
# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information
from __future__ import annotations

import builtins

builtins.__sphinx_build__ = True

from docutils import nodes
from sphinx.util.docutils import SphinxRole
from pathlib import Path

project = "SerialTek"
copyright = Path(__file__).resolve().parent.parent.parent.joinpath("NOTICE").read_text().removeprefix("Copyright ")
author = "SerialTek"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx_click",
    "sphinxcontrib.autodoc_pydantic",
    "sphinx.ext.todo",
    "sphinx_design",
]

templates_path = ["_templates"]
exclude_patterns = []
autodoc_member_order = "bysource"
autodoc_type_aliases = {
    "TimestampLike": "TimestampLike",
    "TicksLike": "TicksLike",
    "ChannelLike": "ChannelLike",
    "ChannelIdPair": "ChannelIdPair",
    "Credentials": "Credentials",
}

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_favicon = "img/favicon.ico"
html_css_files = ["semantic_ui/semantic.min.css"]


class SemanticIconRole(SphinxRole):
    """Role to display a Semantic UI icon."""

    def run(self) -> tuple[list[nodes.Node], list[nodes.system_message]]:
        """Run the role."""
        text = self.text.strip()
        node = nodes.raw("", nodes.Text(f'<i class="{text} icon"></i>'), format="html")
        self.set_source_info(node)
        return [node], []


def setup(app):
    app.add_role("icon", SemanticIconRole())
