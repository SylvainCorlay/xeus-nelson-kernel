# -*- coding: utf-8 -*-

extensions = [
    'jupyterlite_sphinx'
]

master_doc = 'index'
source_suffix = '.rst'

project = 'jupyterlite-xeus-nelson'
copyright = 'JupyterLite Team'
author = 'JupyterLite Team'

exclude_patterns = []

html_theme = "pydata_sphinx_theme"

jupyterlite_dir = "."

html_theme_options = {
   "logo": {
      "image_light": "xeus-nelson.svg",
      "image_dark": "xeus-nelson.svg",
   }
}
