#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *

# PyQt5: TypeError: unhashable type: 'QListWidgetItem'


class HashableQListWidgetItem(QListWidgetItem):

    def __init__(self, *args):
        super(HashableQListWidgetItem, self).__init__(*args)

    def __hash__(self):
        return hash(id(self))
