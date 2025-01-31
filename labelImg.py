#!/usr/bin/env python
# -*- coding: utf-8 -*-
import argparse
import codecs
import os.path
import platform
import shutil
import sys
import webbrowser as wb
from functools import partial

from PySide6.QtGui import *
from PySide6.QtCore import *
from PySide6.QtWidgets import *

from libs.combobox import ComboBox
from libs.default_label_combobox import DefaultLabelComboBox
from libs.resources import *
from libs.constants import *
from libs.utils import *
from libs.settings import Settings
from libs.shape import Shape, DEFAULT_LINE_COLOR, DEFAULT_FILL_COLOR
from libs.stringBundle import StringBundle
from libs.canvas import Canvas
from libs.zoomWidget import ZoomWidget
from libs.lightWidget import LightWidget
from libs.labelDialog import LabelDialog
from libs.colorDialog import ColorDialog
from libs.labelFile import LabelFile, LabelFileError, LabelFileFormat
from libs.toolBar import ToolBar
from libs.pascal_voc_io import PascalVocReader
from libs.pascal_voc_io import XML_EXT
from libs.yolo_io import YoloReader
from libs.yolo_io import TXT_EXT
from libs.create_ml_io import CreateMLReader
from libs.create_ml_io import JSON_EXT
from libs.ustr import ustr
from libs.hashableQListWidgetItem import HashableQListWidgetItem

__appname__ = 'labelImg'


def inverted(color):
    return QColor(*[255 - v for v in color.getRgb()])


def read(filename, default=None):
    """Intenta leer la imagen en `filename`. Retorna QImage o `default` en caso de error."""
    try:
        reader = QImageReader(filename)
        reader.setAutoTransform(True)
        return reader.read()
    except:
        return default


class LabelImgWidget(QWidget):
    """
    Ejemplo de conversión de la ventana principal de QMainWindow a un QWidget,
    conservando la mayor parte de la funcionalidad, menús y herramientas.
    """
    FIT_WINDOW, FIT_WIDTH, MANUAL_ZOOM = list(range(3))

    def __init__(self, default_filename=None, default_prefdef_class_file=None, default_save_dir=None, parent=None):
        super(LabelImgWidget, self).__init__(parent)
        self.setWindowTitle(__appname__)

        # -- Menú y barra de estado "manuales" (porque ya no somos QMainWindow) --
        self.menu_bar = QMenuBar(self)
        self.status_bar = QStatusBar(self)

        # Layout principal en vertical: Menú arriba, contenido en medio, barra de estado abajo
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        # Agregamos el QMenuBar al layout (así queda arriba)
        self.main_layout.setMenuBar(self.menu_bar)

        # Área central con splitter horizontal (imagen a la izquierda, paneles a la derecha)
        self.splitter = QSplitter(self)
        self.splitter.setOrientation(Qt.Horizontal)
        self.main_layout.addWidget(self.splitter)

        # Al final agregamos la barra de estado
        self.main_layout.addWidget(self.status_bar)

        # Configuraciones
        self.settings = Settings()
        self.settings.load()
        settings = self.settings

        self.os_name = platform.system()
        self.string_bundle = StringBundle.get_bundle()
        get_str = lambda str_id: self.string_bundle.get_string(str_id)

        self.default_save_dir = default_save_dir
        self.label_file_format = settings.get(SETTING_LABEL_FILE_FORMAT, LabelFileFormat.PASCAL_VOC)
        self.m_img_list = []
        self.dir_name = None
        self.label_hist = []
        self.last_open_dir = None
        self.cur_img_idx = 0
        self.img_count = len(self.m_img_list)
        self.dirty = False
        self._no_selection_slot = False
        self._beginner = True
        self.screencast = "https://youtu.be/p0nR2YsCY_U"

        # Diálogo de etiquetas
        self.label_dialog = LabelDialog(parent=self, list_item=self.label_hist)

        self.items_to_shapes = {}
        self.shapes_to_items = {}
        self.prev_label_text = ''

        # Predefined classes (opcional)
        # self.load_predefined_classes(default_prefdef_class_file)
        if self.label_hist:
            self.default_label = self.label_hist[0]
        else:
            print("Not found: /data/predefined_classes.txt (optional)")

        self.use_default_label_checkbox = QCheckBox(get_str('useDefaultLabel'))
        self.use_default_label_checkbox.setChecked(False)
        self.default_label_combo_box = DefaultLabelComboBox(self, items=self.label_hist)

        use_default_label_qhbox_layout = QHBoxLayout()
        use_default_label_qhbox_layout.addWidget(self.use_default_label_checkbox)
        use_default_label_qhbox_layout.addWidget(self.default_label_combo_box)
        use_default_label_container = QWidget()
        use_default_label_container.setLayout(use_default_label_qhbox_layout)

        # Botones y checks
        self.diffc_button = QCheckBox(get_str('useDifficult'))
        self.diffc_button.setChecked(False)
        self.diffc_button.stateChanged.connect(self.button_state)
        self.edit_button = QToolButton()
        self.edit_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        # ComboBox de etiquetas únicas
        self.combo_box = ComboBox(self)

        # Lista de etiquetas
        self.label_list = QListWidget()
        self.label_list.itemActivated.connect(self.label_selection_changed)
        self.label_list.itemSelectionChanged.connect(self.label_selection_changed)
        #self.label_list.itemDoubleClicked.connect(self.edit_label)
        self.label_list.itemChanged.connect(self.label_item_changed)

        # Layout para la parte de etiquetado (labels)
        list_layout = QVBoxLayout()
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.addWidget(self.edit_button)
        list_layout.addWidget(self.diffc_button)
        list_layout.addWidget(use_default_label_container)
        list_layout.addWidget(self.combo_box)
        list_layout.addWidget(self.label_list)

        label_list_container = QWidget()
        label_list_container.setLayout(list_layout)

        # Panel derecho superior (labels)
        self.right_side_top = QWidget()
        self.right_side_top_layout = QVBoxLayout(self.right_side_top)
        self.right_side_top_layout.setContentsMargins(0, 0, 0, 0)
        self.right_side_top_layout.addWidget(label_list_container)

        # Lista de ficheros
        self.file_list_widget = QListWidget()
        self.file_list_widget.itemDoubleClicked.connect(self.file_item_double_clicked)

        file_list_layout = QVBoxLayout()
        file_list_layout.setContentsMargins(0, 0, 0, 0)
        file_list_layout.addWidget(self.file_list_widget)
        file_list_container = QWidget()
        file_list_container.setLayout(file_list_layout)

        # Panel derecho inferior (archivos)
        self.right_side_bottom = QWidget()
        self.right_side_bottom_layout = QVBoxLayout(self.right_side_bottom)
        self.right_side_bottom_layout.setContentsMargins(0, 0, 0, 0)
        self.right_side_bottom_layout.addWidget(file_list_container)

        # Splitter vertical a la derecha
        self.right_splitter = QSplitter(self)
        self.right_splitter.setOrientation(Qt.Vertical)
        self.right_splitter.addWidget(self.right_side_top)
        self.right_splitter.addWidget(self.right_side_bottom)

        # Zoom y luz
        self.zoom_widget = ZoomWidget()
        self.light_widget = LightWidget(get_str('lightWidgetTitle'))
        self.color_dialog = ColorDialog(parent=self)

        # Canvas (área de dibujo)
        self.canvas = Canvas(parent=self)
        self.canvas.zoomRequest.connect(self.zoom_request)
        self.canvas.lightRequest.connect(self.light_request)
        self.canvas.set_drawing_shape_to_square(settings.get(SETTING_DRAW_SQUARE, False))

        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setWidgetResizable(True)
        self.scroll_bars = {
            Qt.Vertical: scroll.verticalScrollBar(),
            Qt.Horizontal: scroll.horizontalScrollBar()
        }
        self.scroll_area = scroll
        #self.canvas.scrollRequest.connect(self.scroll_request)
        self.canvas.newShape.connect(self.new_shape)
        self.canvas.shapeMoved.connect(self.set_dirty)
        self.canvas.selectionChanged.connect(self.shape_selection_changed)
        self.canvas.drawingPolygon.connect(self.toggle_drawing_sensitive)

        # Panel izquierdo: sólo el scroll con la imagen
        self.left_side = QWidget()
        self.left_side_layout = QVBoxLayout(self.left_side)
        self.left_side_layout.setContentsMargins(0, 0, 0, 0)
        self.left_side_layout.addWidget(scroll)

        # Agregamos al splitter principal
        self.splitter.addWidget(self.left_side)
        self.splitter.addWidget(self.right_splitter)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)

        # Estado de la aplicación
        self.image = QImage()
        self.file_path = ustr(default_filename)
        self.last_open_dir = None
        self.recent_files = []
        self.max_recent = 7
        self.line_color = None
        self.fill_color = None
        self.zoom_level = 100
        self.fit_window = False
        self.difficult = False

        if settings.get(SETTING_RECENT_FILES):
            self.recent_files = [ustr(i) for i in settings.get(SETTING_RECENT_FILES)]

        # Restauramos tamaño y posición
        size = settings.get(SETTING_WIN_SIZE, QSize(600, 500))
        self.resize(size)

        save_dir = ustr(settings.get(SETTING_SAVE_DIR, None))
        self.last_open_dir = ustr(settings.get(SETTING_LAST_OPEN_DIR, None))
        if self.default_save_dir is None and save_dir is not None and os.path.exists(save_dir):
            self.default_save_dir = save_dir
            self.status("Annotation will be saved to %s" % self.default_save_dir)

        Shape.line_color = self.line_color = QColor(settings.get(SETTING_LINE_COLOR, DEFAULT_LINE_COLOR))
        Shape.fill_color = self.fill_color = QColor(settings.get(SETTING_FILL_COLOR, DEFAULT_FILL_COLOR))
        self.canvas.set_drawing_color(self.line_color)
        Shape.difficult = self.difficult

        def xbool(x):
            return bool(x)

        if xbool(settings.get(SETTING_ADVANCE_MODE, False)):
            self.toggle_advanced_mode(value=True)

        # Menús
        self.menus = {}
        self._create_actions_and_menus()

        self.label_coordinates = QLabel('')
        self.status_bar.addPermanentWidget(self.label_coordinates)

        # Si pasamos un directorio como "file_path"
        if self.file_path and os.path.isdir(self.file_path):
            self.open_dir_dialog(dir_path=self.file_path, silent=True)
        elif self.file_path:
            self.load_file(self.file_path)

    # --------------------------------------------------------------------------
    # Sección de creación de menús y acciones (adaptada de QMainWindow a QMenuBar)
    # --------------------------------------------------------------------------
    def _create_actions_and_menus(self):
        get_str = lambda str_id: self.string_bundle.get_string(str_id)
        action = partial(new_action, self)

        quit_action = action(get_str('quit'), self.close,
                             'Ctrl+Q', 'quit', get_str('quitApp'))

        open_action = action(get_str('openFile'), self.open_file,
                             'Ctrl+O', 'open', get_str('openFileDetail'))

        open_dir_action = action(get_str('openDir'), self.open_dir_dialog,
                                 'Ctrl+u', 'open', get_str('openDir'))

        """ change_save_dir_action = action(get_str('changeSaveDir'), self.change_save_dir_dialog,
                                        'Ctrl+r', 'open', get_str('changeSavedAnnotationDir'))

        open_annotation_action = action(get_str('openAnnotation'), self.open_annotation_dialog,
                                        'Ctrl+Shift+O', 'open', get_str('openAnnotationDetail')) """

        copy_prev_bounding_action = action(get_str('copyPrevBounding'), self.copy_previous_bounding_boxes,
                                           'Ctrl+v', 'copy', get_str('copyPrevBounding'))

        open_next_image_action = action(get_str('nextImg'), self.open_next_image,
                                        'd', 'next', get_str('nextImgDetail'))

        open_prev_image_action = action(get_str('prevImg'), self.open_prev_image,
                                        'a', 'prev', get_str('prevImgDetail'))

        verify_action = action(get_str('verifyImg'), self.verify_image,
                               'space', 'verify', get_str('verifyImgDetail'))

        save_action = action(get_str('save'), self.save_file,
                             'Ctrl+S', 'save', get_str('saveDetail'), enabled=False)

        save_as_action = action(get_str('saveAs'), self.save_file_as,
                                'Ctrl+Shift+S', 'save-as', get_str('saveAsDetail'), enabled=False)

        close_action = action(get_str('closeCur'), self.close_file,
                              'Ctrl+W', 'close', get_str('closeCurDetail'))

        delete_image_action = action(get_str('deleteImg'), self.delete_image,
                                     'Ctrl+Shift+D', 'close', get_str('deleteImgDetail'))

        reset_all_action = action(get_str('resetAll'), self.reset_all,
                                  None, 'resetall', get_str('resetAllDetail'))

        color1_action = action(get_str('boxLineColor'), self.choose_color1,
                               'Ctrl+L', 'color_line', get_str('boxLineColorDetail'))

        create_mode_action = action(get_str('crtBox'), self.set_create_mode,
                                    'w', 'new', get_str('crtBoxDetail'), enabled=False)

        edit_mode_action = action(get_str('editBox'), self.set_edit_mode,
                                  'Ctrl+J', 'edit', get_str('editBoxDetail'), enabled=False)

        create_action = action(get_str('crtBox'), self.create_shape,
                               'w', 'new', get_str('crtBoxDetail'), enabled=False)
        delete_action = action(get_str('delBox'), self.delete_selected_shape,
                               'Delete', 'delete', get_str('delBoxDetail'), enabled=False)
        copy_action = action(get_str('dupBox'), self.copy_selected_shape,
                             'Ctrl+D', 'copy', get_str('dupBoxDetail'), enabled=False)

        advanced_mode_action = action(get_str('advancedMode'), self.toggle_advanced_mode,
                                      'Ctrl+Shift+A', 'expert', get_str('advancedModeDetail'),
                                      checkable=True)

        hide_all_action = action(get_str('hideAllBox'), partial(self.toggle_polygons, False),
                                 'Ctrl+H', 'hide', get_str('hideAllBoxDetail'),
                                 enabled=False)
        show_all_action = action(get_str('showAllBox'), partial(self.toggle_polygons, True),
                                 'Ctrl+A', 'hide', get_str('showAllBoxDetail'),
                                 enabled=False)

        help_default_action = action(get_str('tutorialDefault'), self.show_default_tutorial_dialog,
                                     None, 'help', get_str('tutorialDetail'))
        show_info_action = action(get_str('info'), self.show_info_dialog,
                                  None, 'help', get_str('info'))
        show_shortcut_action = action(get_str('shortcut'), self.show_shortcuts_dialog,
                                      None, 'help', get_str('shortcut'))

        # Zoom y Light
        self.zoom_widget.setEnabled(False)
        zoom_in_action = action(get_str('zoomin'), partial(self.add_zoom, 10),
                                'Ctrl++', 'zoom-in', get_str('zoominDetail'), enabled=False)
        zoom_out_action = action(get_str('zoomout'), partial(self.add_zoom, -10),
                                 'Ctrl+-', 'zoom-out', get_str('zoomoutDetail'), enabled=False)
        zoom_org_action = action(get_str('originalsize'), partial(self.set_zoom, 100),
                                 'Ctrl+=', 'zoom', get_str('originalsizeDetail'), enabled=False)
        fit_window_action = action(get_str('fitWin'), self.set_fit_window,
                                   'Ctrl+F', 'fit-window', get_str('fitWinDetail'),
                                   checkable=True, enabled=False)
        fit_width_action = action(get_str('fitWidth'), self.set_fit_width,
                                  'Ctrl+Shift+F', 'fit-width', get_str('fitWidthDetail'),
                                  checkable=True, enabled=False)

        self.light_widget.setEnabled(False)
        light_brighten_action = action(get_str('lightbrighten'), partial(self.add_light, 10),
                                       'Ctrl+Shift++', 'light_lighten', get_str('lightbrightenDetail'), enabled=False)
        light_darken_action = action(get_str('lightdarken'), partial(self.add_light, -10),
                                     'Ctrl+Shift+-', 'light_darken', get_str('lightdarkenDetail'), enabled=False)
        light_org_action = action(get_str('lightreset'), partial(self.set_light, 50),
                                  'Ctrl+Shift+=', 'light_reset', get_str('lightresetDetail'),
                                  checkable=True, enabled=False)
        light_org_action.setChecked(True)

        """ edit_action = action(get_str('editLabel'), self.edit_label,
                             'Ctrl+E', 'edit', get_str('editLabelDetail'),
                             enabled=False) """
        #self.edit_button.setDefaultAction(edit_action)

        shape_line_color_action = action(get_str('shapeLineColor'), self.choose_shape_line_color,
                                         icon='color_line', tip=get_str('shapeLineColorDetail'),
                                         enabled=False)
        shape_fill_color_action = action(get_str('shapeFillColor'), self.choose_shape_fill_color,
                                         icon='color', tip=get_str('shapeFillColorDetail'),
                                         enabled=False)

        # Check y acción para dibujar cuadrados
        self.draw_squares_option = QAction(get_str('drawSquares'), self)
        self.draw_squares_option.setShortcut('Ctrl+Shift+R')
        self.draw_squares_option.setCheckable(True)
        self.draw_squares_option.setChecked(self.settings.get(SETTING_DRAW_SQUARE, False))
        self.draw_squares_option.triggered.connect(self.toggle_draw_square)

        # Auto save
        self.auto_saving = QAction(get_str('autoSaveMode'), self)
        self.auto_saving.setCheckable(True)
        self.auto_saving.setChecked(self.settings.get(SETTING_AUTO_SAVE, False))

        # Single class mode
        self.single_class_mode = QAction(get_str('singleClsMode'), self)
        self.single_class_mode.setShortcut("Ctrl+Shift+S")
        self.single_class_mode.setCheckable(True)
        self.single_class_mode.setChecked(self.settings.get(SETTING_SINGLE_CLASS, False))

        # Opción para mostrar/ocultar texto de la etiqueta
        self.display_label_option = QAction(get_str('displayLabel'), self)
        self.display_label_option.setShortcut("Ctrl+Shift+P")
        self.display_label_option.setCheckable(True)
        self.display_label_option.setChecked(self.settings.get(SETTING_PAINT_LABEL, False))
        self.display_label_option.triggered.connect(self.toggle_paint_labels_option)

        # Guarda referencias para usarlas en el código
        self.actions = Struct(
            save=save_action,
            saveAs=save_as_action,
            open=open_action,
            close=close_action,
            resetAll=reset_all_action,
            deleteImg=delete_image_action,
            lineColor=color1_action,
            create=create_action,
            delete=delete_action,
            edit=edit_action,
            copy=copy_action,
            createMode=create_mode_action,
            editMode=edit_mode_action,
            advancedMode=advanced_mode_action,
            shapeLineColor=shape_line_color_action,
            shapeFillColor=shape_fill_color_action,
            zoomIn=zoom_in_action,
            zoomOut=zoom_out_action,
            zoomOrg=zoom_org_action,
            fitWindow=fit_window_action,
            fitWidth=fit_width_action,
            lightBrighten=light_brighten_action,
            lightDarken=light_darken_action,
            lightOrg=light_org_action,
            onShapesPresent=[],  # Se llenará luego
        )

        # Menú "Archivo"
        file_menu = self.menu_bar.addMenu(get_str('menu_file'))
        add_actions(file_menu, (
            open_action,
            open_dir_action,
            change_save_dir_action,
            open_annotation_action,
            copy_prev_bounding_action,
            save_action,
            save_as_action,
            close_action,
            reset_all_action,
            delete_image_action,
            quit_action
        ))

        # Menú "Editar"
        edit_menu = self.menu_bar.addMenu(get_str('menu_edit'))
        add_actions(edit_menu, (
            edit_action,
            copy_action,
            delete_action,
            None,
            color1_action,
            self.draw_squares_option
        ))

        # Menú "Ver"
        view_menu = self.menu_bar.addMenu(get_str('menu_view'))
        add_actions(view_menu, (
            self.auto_saving,
            self.single_class_mode,
            self.display_label_option,
            advanced_mode_action,
            None,
            zoom_in_action,
            zoom_out_action,
            zoom_org_action,
            None,
            fit_window_action,
            fit_width_action,
            None,
            self.actions.lightBrighten,
            self.actions.lightDarken,
            self.actions.lightOrg
        ))

        # Menú "Ayuda"
        help_menu = self.menu_bar.addMenu(get_str('menu_help'))
        add_actions(help_menu, (
            help_default_action,
            show_info_action,
            show_shortcut_action
        ))

        # Para configuraciones extra al cargar shapes
        self.actions.onShapesPresent = (save_as_action, )

    # ----------------------------------
    # Métodos principales de funcionalidad
    # ----------------------------------
    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Control:
            self.canvas.set_drawing_shape_to_square(False)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Control:
            self.canvas.set_drawing_shape_to_square(True)

    def status(self, message, delay=5000):
        """Muestra un mensaje en la barra de estado."""
        self.status_bar.showMessage(message, delay)

    def reset_state(self):
        self.items_to_shapes.clear()
        self.shapes_to_items.clear()
        self.label_list.clear()
        self.file_path = None
        self.image_data = None
        self.label_file = None
        self.canvas.reset_state()
        self.label_coordinates.clear()
        self.combo_box.cb.clear()

    def may_continue(self):
        if not self.dirty:
            return True
        else:
            discard_changes = self.discard_changes_dialog()
            if discard_changes == QMessageBox.No:
                return True
            elif discard_changes == QMessageBox.Yes:
                self.save_file()
                return True
            else:
                return False

    def discard_changes_dialog(self):
        yes, no, cancel = QMessageBox.Yes, QMessageBox.No, QMessageBox.Cancel
        msg = (u'You have unsaved changes, would you like to save them and proceed?\n'
               u'Click "No" to undo all changes.')
        return QMessageBox.warning(self, u'Attention', msg, yes | no | cancel)

    def close(self):
        """En un QWidget, close() cerrará este widget."""
        if not self.may_continue():
            return
        # Salvamos configuraciones
        settings = self.settings
        settings[SETTING_FILENAME] = self.file_path if (self.file_path and not os.path.isdir(self.file_path)) else ''
        settings[SETTING_WIN_SIZE] = self.size()
        settings[SETTING_LINE_COLOR] = self.line_color
        settings[SETTING_FILL_COLOR] = self.fill_color
        settings[SETTING_RECENT_FILES] = self.recent_files
        settings[SETTING_ADVANCE_MODE] = not self._beginner
        if self.default_save_dir and os.path.exists(self.default_save_dir):
            settings[SETTING_SAVE_DIR] = ustr(self.default_save_dir)
        else:
            settings[SETTING_SAVE_DIR] = ''

        if self.last_open_dir and os.path.exists(self.last_open_dir):
            settings[SETTING_LAST_OPEN_DIR] = self.last_open_dir
        else:
            settings[SETTING_LAST_OPEN_DIR] = ''

        settings[SETTING_AUTO_SAVE] = self.auto_saving.isChecked()
        settings[SETTING_SINGLE_CLASS] = self.single_class_mode.isChecked()
        settings[SETTING_PAINT_LABEL] = self.display_label_option.isChecked()
        settings[SETTING_DRAW_SQUARE] = self.draw_squares_option.isChecked()
        settings[SETTING_LABEL_FILE_FORMAT] = self.label_file_format
        settings.save()

        super(LabelImgWidget, self).close()

    # ----------------------------------
    # Funciones asociadas a la carga/guardado de archivos
    # ----------------------------------
    def load_file(self, file_path=None):
        self.reset_state()
        self.canvas.setEnabled(False)
        if file_path is None:
            file_path = self.settings.get(SETTING_FILENAME)
        file_path = ustr(file_path)
        unicode_file_path = os.path.abspath(ustr(file_path))

        # Si tenemos lista de archivos, marcamos en la lista
        if unicode_file_path and self.file_list_widget.count() > 0:
            if unicode_file_path in self.m_img_list:
                index = self.m_img_list.index(unicode_file_path)
                file_widget_item = self.file_list_widget.item(index)
                file_widget_item.setSelected(True)
            else:
                self.file_list_widget.clear()
                self.m_img_list.clear()

        if unicode_file_path and os.path.exists(unicode_file_path):
            if LabelFile.is_label_file(unicode_file_path):
                try:
                    self.label_file = LabelFile(unicode_file_path)
                except LabelFileError as e:
                    self.error_message(u'Error opening file',
                                       (u"<p><b>%s</b></p>"
                                        u"<p>Make sure <i>%s</i> is a valid label file.") % (e, unicode_file_path))
                    self.status("Error reading %s" % unicode_file_path)
                    return False
                self.image_data = self.label_file.image_data
                self.line_color = QColor(*self.label_file.lineColor)
                self.fill_color = QColor(*self.label_file.fillColor)
                self.canvas.verified = self.label_file.verified
            else:
                self.image_data = read(unicode_file_path, None)
                self.label_file = None
                self.canvas.verified = False

            if isinstance(self.image_data, QImage):
                image = self.image_data
            else:
                image = QImage.fromData(self.image_data)

            if image.isNull():
                self.error_message(u'Error opening file',
                                   u"<p>Make sure <i>%s</i> is a valid image file." % unicode_file_path)
                self.status("Error reading %s" % unicode_file_path)
                return False

            self.status("Loaded %s" % os.path.basename(unicode_file_path))
            self.image = image
            self.file_path = unicode_file_path
            self.canvas.load_pixmap(QPixmap.fromImage(image))
            if self.label_file:
                self.load_labels(self.label_file.shapes)
            self.set_clean()
            self.canvas.setEnabled(True)
            self.adjust_scale(initial=True)
            self.paint_canvas()
            self.add_recent_file(self.file_path)
            self.show_bounding_box_from_annotation_file(self.file_path)
            counter = self.counter_str()
            self.setWindowTitle(__appname__ + ' ' + file_path + ' ' + counter)

            if self.label_list.count():
                self.label_list.setCurrentItem(self.label_list.item(self.label_list.count() - 1))
                self.label_list.item(self.label_list.count() - 1).setSelected(True)

            self.canvas.setFocus()
            return True
        return False

    def show_bounding_box_from_annotation_file(self, file_path):
        if self.default_save_dir is not None:
            basename = os.path.basename(os.path.splitext(file_path)[0])
            xml_path = os.path.join(self.default_save_dir, basename + XML_EXT)
            txt_path = os.path.join(self.default_save_dir, basename + TXT_EXT)
            json_path = os.path.join(self.default_save_dir, basename + JSON_EXT)
            if os.path.isfile(xml_path):
                self.load_pascal_xml_by_filename(xml_path)
            elif os.path.isfile(txt_path):
                self.load_yolo_txt_by_filename(txt_path)
            elif os.path.isfile(json_path):
                self.load_create_ml_json_by_filename(json_path, file_path)
        else:
            xml_path = os.path.splitext(file_path)[0] + XML_EXT
            txt_path = os.path.splitext(file_path)[0] + TXT_EXT
            json_path = os.path.splitext(file_path)[0] + JSON_EXT
            if os.path.isfile(xml_path):
                self.load_pascal_xml_by_filename(xml_path)
            elif os.path.isfile(txt_path):
                self.load_yolo_txt_by_filename(txt_path)
            elif os.path.isfile(json_path):
                self.load_create_ml_json_by_filename(json_path, file_path)

    def scan_all_images(self, folder_path):
        extensions = ['.%s' % fmt.data().decode("ascii").lower() for fmt in QImageReader.supportedImageFormats()]
        images = []
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                if file.lower().endswith(tuple(extensions)):
                    relative_path = os.path.join(root, file)
                    path = ustr(os.path.abspath(relative_path))
                    images.append(path)
        natural_sort(images, key=lambda x: x.lower())
        return images

    def open_dir_dialog(self, _value=False, dir_path=None, silent=False):
        if not self.may_continue():
            return
        default_open_dir_path = dir_path if dir_path else '.'
        if self.last_open_dir and os.path.exists(self.last_open_dir):
            default_open_dir_path = self.last_open_dir
        else:
            default_open_dir_path = os.path.dirname(self.file_path) if self.file_path else '.'
        if not silent:
            target_dir_path = ustr(QFileDialog.getExistingDirectory(
                self, '%s - Open Directory' % __appname__, default_open_dir_path,
                QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks))
        else:
            target_dir_path = ustr(default_open_dir_path)
        self.last_open_dir = target_dir_path
        self.import_dir_images(target_dir_path)
        self.default_save_dir = target_dir_path
        if self.file_path:
            self.show_bounding_box_from_annotation_file(file_path=self.file_path)

    def import_dir_images(self, dir_path):
        if not self.may_continue() or not dir_path:
            return
        self.last_open_dir = dir_path
        self.dir_name = dir_path
        self.file_path = None
        self.file_list_widget.clear()
        self.m_img_list = self.scan_all_images(dir_path)
        self.img_count = len(self.m_img_list)
        self.open_next_image()
        for imgPath in self.m_img_list:
            item = QListWidgetItem(imgPath)
            self.file_list_widget.addItem(item)

    def open_file(self, _value=False):
        if not self.may_continue():
            return
        path = os.path.dirname(ustr(self.file_path)) if self.file_path else '.'
        formats = ['*.%s' % fmt.data().decode("ascii").lower() for fmt in QImageReader.supportedImageFormats()]
        filters = "Image & Label files (%s)" % ' '.join(formats + ['*%s' % LabelFile.suffix])
        filename, _ = QFileDialog.getOpenFileName(self, '%s - Choose Image or Label file' % __appname__, path, filters)
        if filename:
            self.cur_img_idx = 0
            self.img_count = 1
            self.load_file(filename)

    def save_file(self, _value=False):
        if self.default_save_dir is not None and len(ustr(self.default_save_dir)):
            if self.file_path:
                image_file_name = os.path.basename(self.file_path)
                saved_file_name = os.path.splitext(image_file_name)[0]
                saved_path = os.path.join(ustr(self.default_save_dir), saved_file_name)
                self._save_file(saved_path)
        else:
            image_file_dir = os.path.dirname(self.file_path)
            image_file_name = os.path.basename(self.file_path)
            saved_file_name = os.path.splitext(image_file_name)[0]
            saved_path = os.path.join(image_file_dir, saved_file_name)
            self._save_file(saved_path if self.label_file else self.save_file_dialog(remove_ext=False))

    def save_file_as(self, _value=False):
        assert not self.image.isNull(), "cannot save empty image"
        self._save_file(self.save_file_dialog())

    def save_file_dialog(self, remove_ext=True):
        caption = '%s - Choose File' % __appname__
        filters = 'File (*%s)' % LabelFile.suffix
        open_dialog_path = os.path.dirname(self.file_path) if self.file_path else '.'
        dlg = QFileDialog(self, caption, open_dialog_path, filters)
        dlg.setDefaultSuffix(LabelFile.suffix[1:])
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        filename_without_extension = os.path.splitext(self.file_path)[0] if self.file_path else ''
        dlg.selectFile(filename_without_extension)
        if dlg.exec_():
            full_file_path = ustr(dlg.selectedFiles()[0])
            if remove_ext:
                return os.path.splitext(full_file_path)[0]
            else:
                return full_file_path
        return ''

    def _save_file(self, annotation_file_path):
        if annotation_file_path and self.save_labels(annotation_file_path):
            self.set_clean()
            self.status('Saved to %s' % annotation_file_path)

    def close_file(self, _value=False):
        if not self.may_continue():
            return
        self.reset_state()
        self.set_clean()
        self.canvas.setEnabled(False)
        self.actions.saveAs.setEnabled(False)

    def delete_image(self):
        delete_path = self.file_path
        if delete_path is not None:
            idx = self.cur_img_idx
            if os.path.exists(delete_path):
                os.remove(delete_path)
            self.import_dir_images(self.last_open_dir)
            if self.img_count > 0:
                self.cur_img_idx = min(idx, self.img_count - 1)
                filename = self.m_img_list[self.cur_img_idx]
                self.load_file(filename)
            else:
                self.close_file()

    def reset_all(self):
        self.settings.reset()
        self.close()
        process = QProcess()
        process.startDetached(sys.executable, [os.path.abspath(__file__)])

    def copy_previous_bounding_boxes(self):
        if not self.m_img_list:
            return
        current_index = self.m_img_list.index(self.file_path)
        if current_index - 1 >= 0:
            prev_file_path = self.m_img_list[current_index - 1]
            self.show_bounding_box_from_annotation_file(prev_file_path)
            self.save_file()

    # -----------------
    # Zoom y Light
    # -----------------
    def set_zoom(self, value):
        self.actions.fitWidth.setChecked(False)
        self.actions.fitWindow.setChecked(False)
        self.zoom_mode = self.MANUAL_ZOOM
        self.zoom_widget.setValue(int(value))

    def add_zoom(self, increment=10):
        self.set_zoom(self.zoom_widget.value() + increment)

    def zoom_request(self, delta):
        h_bar = self.scroll_bars[Qt.Horizontal]
        v_bar = self.scroll_bars[Qt.Vertical]
        h_bar_max = h_bar.maximum()
        v_bar_max = v_bar.maximum()

        cursor = QCursor()
        pos = cursor.pos()
        relative_pos = self.mapFromGlobal(pos)
        cursor_x = relative_pos.x()
        cursor_y = relative_pos.y()

        w = self.scroll_area.width()
        h = self.scroll_area.height()

        margin = 0.1
        move_x = (cursor_x - margin * w) / (w - 2 * margin * w)
        move_y = (cursor_y - margin * h) / (h - 2 * margin * h)
        move_x = min(max(move_x, 0), 1)
        move_y = min(max(move_y, 0), 1)

        units = delta // (8 * 15)
        scale = 10
        self.add_zoom(scale * units)

        d_h_bar_max = h_bar.maximum() - h_bar_max
        d_v_bar_max = v_bar.maximum() - v_bar_max

        new_h_bar_value = int(h_bar.value() + move_x * d_h_bar_max)
        new_v_bar_value = int(v_bar.value() + move_y * d_v_bar_max)
        h_bar.setValue(new_h_bar_value)
        v_bar.setValue(new_v_bar_value)

    def set_light(self, value):
        self.actions.lightOrg.setChecked(int(value) == 50)
        self.light_widget.setValue(int(value))

    def add_light(self, increment=10):
        self.set_light(self.light_widget.value() + increment)

    def light_request(self, delta):
        self.add_light(5 * delta // (8 * 15))

    def set_fit_window(self, value=True):
        if value:
            self.actions.fitWidth.setChecked(False)
        self.zoom_mode = self.FIT_WINDOW if value else self.MANUAL_ZOOM
        self.adjust_scale()

    def set_fit_width(self, value=True):
        if value:
            self.actions.fitWindow.setChecked(False)
        self.zoom_mode = self.FIT_WIDTH if value else self.MANUAL_ZOOM
        self.adjust_scale()

    def adjust_scale(self, initial=False):
        value = self.scalers[self.FIT_WINDOW if initial else self.zoom_mode]()
        self.zoom_widget.setValue(int(100 * value))

    def scale_fit_window(self):
        e = 2.0
        w1 = self.scroll_area.width() - e
        h1 = self.scroll_area.height() - e
        a1 = w1 / h1
        w2 = self.canvas.pixmap.width() - 0.0
        h2 = self.canvas.pixmap.height() - 0.0
        a2 = w2 / h2
        return w1 / w2 if a2 >= a1 else h1 / h2

    def scale_fit_width(self):
        w = self.scroll_area.width() - 2.0
        return w / self.canvas.pixmap.width()

    @property
    def scalers(self):
        return {
            self.FIT_WINDOW: self.scale_fit_window,
            self.FIT_WIDTH: self.scale_fit_width,
            self.MANUAL_ZOOM: lambda: 1,
        }

    def paint_canvas(self):
        if self.image.isNull():
            return
        self.canvas.scale = 0.01 * self.zoom_widget.value()
        self.canvas.overlay_color = self.light_widget.color()
        self.canvas.label_font_size = int(0.02 * max(self.image.width(), self.image.height()))
        self.canvas.adjustSize()
        self.canvas.update()

    def resizeEvent(self, event):
        if self.canvas and not self.image.isNull() and self.zoom_mode != self.MANUAL_ZOOM:
            self.adjust_scale()
        super(LabelImgWidget, self).resizeEvent(event)

    # --------------------------------------------------------------------------
    # Funciones relacionadas con las formas y etiquetas (shapes)
    # --------------------------------------------------------------------------
    def no_shapes(self):
        return not self.items_to_shapes

    def shape_selection_changed(self, selected=False):
        if self._no_selection_slot:
            self._no_selection_slot = False
        else:
            shape = self.canvas.selected_shape
            if shape:
                self.shapes_to_items[shape].setSelected(True)
            else:
                self.label_list.clearSelection()
        self.actions.delete.setEnabled(selected)
        self.actions.copy.setEnabled(selected)
        self.actions.edit.setEnabled(selected)
        self.actions.shapeLineColor.setEnabled(selected)
        self.actions.shapeFillColor.setEnabled(selected)

    def add_label(self, shape):
        shape.paint_label = self.display_label_option.isChecked()
        item = HashableQListWidgetItem(shape.label)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        item.setBackground(generate_color_by_text(shape.label))
        self.items_to_shapes[item] = shape
        self.shapes_to_items[shape] = item
        self.label_list.addItem(item)
        for action in self.actions.onShapesPresent:
            action.setEnabled(True)
        self.update_combo_box()

    def remove_label(self, shape):
        if shape is None:
            return
        item = self.shapes_to_items[shape]
        self.label_list.takeItem(self.label_list.row(item))
        del self.shapes_to_items[shape]
        del self.items_to_shapes[item]
        self.update_combo_box()

    def load_labels(self, shapes):
        s = []
        for label, points, line_color, fill_color, difficult in shapes:
            shape = Shape(label=label)
            for x, y in points:
                x, y, snapped = self.canvas.snap_point_to_canvas(x, y)
                if snapped:
                    self.set_dirty()
                shape.add_point(QPointF(x, y))
            shape.difficult = difficult
            shape.close()
            s.append(shape)
            if line_color:
                shape.line_color = QColor(*line_color)
            else:
                shape.line_color = generate_color_by_text(label)
            if fill_color:
                shape.fill_color = QColor(*fill_color)
            else:
                shape.fill_color = generate_color_by_text(label)
            self.add_label(shape)
        self.canvas.load_shapes(s)

    def update_combo_box(self):
        items_text_list = [str(self.label_list.item(i).text()) for i in range(self.label_list.count())]
        unique_text_list = list(set(items_text_list))
        unique_text_list.append("")
        unique_text_list.sort()
        self.combo_box.update_items(unique_text_list)

    def save_labels(self, annotation_file_path):
        annotation_file_path = ustr(annotation_file_path)
        if not self.label_file:
            self.label_file = LabelFile()
            self.label_file.verified = self.canvas.verified

        def format_shape(s):
            return dict(label=s.label,
                        line_color=s.line_color.getRgb(),
                        fill_color=s.fill_color.getRgb(),
                        points=[(p.x(), p.y()) for p in s.points],
                        difficult=s.difficult)

        shapes = [format_shape(shape) for shape in self.canvas.shapes]
        try:
            if self.label_file_format == LabelFileFormat.PASCAL_VOC:
                if annotation_file_path[-4:].lower() != ".xml":
                    annotation_file_path += XML_EXT
                self.label_file.save_pascal_voc_format(
                    annotation_file_path, shapes, self.file_path, self.image_data,
                    self.line_color.getRgb(), self.fill_color.getRgb()
                )
            elif self.label_file_format == LabelFileFormat.YOLO:
                if annotation_file_path[-4:].lower() != ".txt":
                    annotation_file_path += TXT_EXT
                self.label_file.save_yolo_format(
                    annotation_file_path, shapes, self.file_path, self.image_data,
                    self.label_hist, self.line_color.getRgb(), self.fill_color.getRgb()
                )
            elif self.label_file_format == LabelFileFormat.CREATE_ML:
                if annotation_file_path[-5:].lower() != ".json":
                    annotation_file_path += JSON_EXT
                self.label_file.save_create_ml_format(
                    annotation_file_path, shapes, self.file_path, self.image_data,
                    self.label_hist, self.line_color.getRgb(), self.fill_color.getRgb()
                )
            else:
                self.label_file.save(
                    annotation_file_path, shapes, self.file_path, self.image_data,
                    self.line_color.getRgb(), self.fill_color.getRgb()
                )
            print('Image:{0} -> Annotation:{1}'.format(self.file_path, annotation_file_path))
            return True
        except LabelFileError as e:
            self.error_message(u'Error saving label data', u'<b>%s</b>' % e)
            return False

    def file_item_double_clicked(self, item=None):
        self.cur_img_idx = self.m_img_list.index(ustr(item.text()))
        filename = self.m_img_list[self.cur_img_idx]
        if filename:
            self.load_file(filename)

    # ------------------------------------------------------------------------------------
    # Eventos y callbacks
    # ------------------------------------------------------------------------------------
    def button_state(self, item=None):
        if not self.canvas.editing():
            return
        item = self.current_item()
        if not item:
            if self.label_list.count() > 0:
                item = self.label_list.item(self.label_list.count() - 1)
            else:
                return
        difficult = self.diffc_button.isChecked()
        try:
            shape = self.items_to_shapes[item]
        except:
            return
        try:
            if difficult != shape.difficult:
                shape.difficult = difficult
                self.set_dirty()
            else:
                self.canvas.set_shape_visible(shape, item.checkState() == Qt.Checked)
        except:
            pass

    def current_item(self):
        items = self.label_list.selectedItems()
        if items:
            return items[0]
        return None

    def label_selection_changed(self):
        item = self.current_item()
        if item and self.canvas.editing():
            self._no_selection_slot = True
            self.canvas.select_shape(self.items_to_shapes[item])
            shape = self.items_to_shapes[item]
            self.diffc_button.setChecked(shape.difficult)

    def label_item_changed(self, item):
        shape = self.items_to_shapes[item]
        label = item.text()
        if label != shape.label:
            shape.label = label
            shape.line_color = generate_color_by_text(shape.label)
            self.set_dirty()
        else:
            self.canvas.set_shape_visible(shape, item.checkState() == Qt.Checked)

    def new_shape(self):
        if not self.use_default_label_checkbox.isChecked():
            if len(self.label_hist) > 0:
                self.label_dialog = LabelDialog(parent=self, list_item=self.label_hist)
            if self.single_class_mode.isChecked() and getattr(self, "lastLabel", None):
                text = self.lastLabel
            else:
                text = self.label_dialog.pop_up(text=self.prev_label_text)
                self.lastLabel = text
        else:
            text = getattr(self, "default_label", "")

        self.diffc_button.setChecked(False)
        if text is not None:
            self.prev_label_text = text
            generate_color_ = generate_color_by_text(text)
            shape = self.canvas.set_last_label(text, generate_color_, generate_color_)
            self.add_label(shape)
            if self._beginner:
                self.canvas.set_editing(True)
                self.actions.create.setEnabled(True)
            else:
                self.actions.editMode.setEnabled(True)
            self.set_dirty()
            if text not in self.label_hist:
                self.label_hist.append(text)
        else:
            self.canvas.reset_all_lines()

    def create_shape(self):
        assert self._beginner
        self.canvas.set_editing(False)
        self.actions.create.setEnabled(False)

    def toggle_drawing_sensitive(self, drawing=True):
        self.actions.editMode.setEnabled(not drawing)
        if not drawing and self._beginner:
            self.canvas.set_editing(True)
            self.canvas.restore_cursor()
            self.actions.create.setEnabled(True)

    def toggle_draw_mode(self, edit=True):
        self.canvas.set_editing(edit)
        self.actions.createMode.setEnabled(edit)
        self.actions.editMode.setEnabled(not edit)

    def set_create_mode(self):
        assert not self._beginner
        self.toggle_draw_mode(False)

    def set_edit_mode(self):
        assert not self._beginner
        self.toggle_draw_mode(True)
        self.label_selection_changed()

    def toggle_advanced_mode(self, value=True):
        self._beginner = not value
        self.canvas.set_editing(True)
        self.edit_button.setVisible(not value)
        if value:
            self.actions.createMode.setEnabled(True)
            self.actions.editMode.setEnabled(False)
        else:
            pass

    def copy_selected_shape(self):
        self.add_label(self.canvas.copy_selected_shape())
        self.shape_selection_changed(True)

    def delete_selected_shape(self):
        self.remove_label(self.canvas.delete_selected())
        self.set_dirty()
        if self.no_shapes():
            for action in self.actions.onShapesPresent:
                action.setEnabled(False)

    def choose_color1(self):
        color = self.color_dialog.getColor(self.line_color, u'Choose line color',
                                           default=DEFAULT_LINE_COLOR)
        if color:
            self.line_color = color
            Shape.line_color = color
            self.canvas.set_drawing_color(color)
            self.canvas.update()
            self.set_dirty()

    def choose_shape_line_color(self):
        color = self.color_dialog.getColor(self.line_color, u'Choose Line Color',
                                           default=DEFAULT_LINE_COLOR)
        if color:
            self.canvas.selected_shape.line_color = color
            self.canvas.update()
            self.set_dirty()

    def choose_shape_fill_color(self):
        color = self.color_dialog.getColor(self.fill_color, u'Choose Fill Color',
                                           default=DEFAULT_FILL_COLOR)
        if color:
            self.canvas.selected_shape.fill_color = color
            self.canvas.update()
            self.set_dirty()

    def copy_shape(self):
        if self.canvas.selected_shape is None:
            return
        self.canvas.end_move(copy=True)
        self.add_label(self.canvas.selected_shape)
        self.set_dirty()

    def move_shape(self):
        self.canvas.end_move(copy=False)
        self.set_dirty()

    def toggle_polygons(self, value):
        for item, shape in self.items_to_shapes.items():
            item.setCheckState(Qt.Checked if value else Qt.Unchecked)

    def verify_image(self, _value=False):
        if self.file_path is not None:
            try:
                self.label_file.toggle_verify()
            except AttributeError:
                self.save_file()
                if self.label_file is not None:
                    self.label_file.toggle_verify()
                else:
                    return
            self.canvas.verified = self.label_file.verified
            self.paint_canvas()
            self.save_file()

    def open_prev_image(self, _value=False):
        if self.auto_saving.isChecked():
            if self.default_save_dir is not None:
                if self.dirty is True:
                    self.save_file()
            else:
                self.change_save_dir_dialog()
                return

        if not self.may_continue():
            return
        if self.img_count <= 0:
            return
        if self.file_path is None:
            return
        if self.cur_img_idx - 1 >= 0:
            self.cur_img_idx -= 1
            filename = self.m_img_list[self.cur_img_idx]
            if filename:
                self.load_file(filename)

    def open_next_image(self, _value=False):
        if self.auto_saving.isChecked():
            if self.default_save_dir is not None:
                if self.dirty is True:
                    self.save_file()
            else:
                self.change_save_dir_dialog()
                return
        if not self.may_continue():
            return
        if self.img_count <= 0:
            return
        if not self.m_img_list:
            return
        filename = None
        if self.file_path is None:
            filename = self.m_img_list[0]
            self.cur_img_idx = 0
        else:
            if self.cur_img_idx + 1 < self.img_count:
                self.cur_img_idx += 1
                filename = self.m_img_list[self.cur_img_idx]
        if filename:
            self.load_file(filename)

    def load_pascal_xml_by_filename(self, xml_path):
        if self.file_path is None:
            return
        if not os.path.isfile(xml_path):
            return
        self.set_format(FORMAT_PASCALVOC)
        t_voc_parse_reader = PascalVocReader(xml_path)
        shapes = t_voc_parse_reader.get_shapes()
        self.load_labels(shapes)
        self.canvas.verified = t_voc_parse_reader.verified

    def load_yolo_txt_by_filename(self, txt_path):
        if self.file_path is None:
            return
        if not os.path.isfile(txt_path):
            return
        self.set_format(FORMAT_YOLO)
        t_yolo_parse_reader = YoloReader(txt_path, self.image)
        shapes = t_yolo_parse_reader.get_shapes()
        self.load_labels(shapes)
        self.canvas.verified = t_yolo_parse_reader.verified

    def load_create_ml_json_by_filename(self, json_path, file_path):
        if self.file_path is None:
            return
        if not os.path.isfile(json_path):
            return
        self.set_format(FORMAT_CREATEML)
        create_ml_parse_reader = CreateMLReader(json_path, file_path)
        shapes = create_ml_parse_reader.get_shapes()
        self.load_labels(shapes)
        self.canvas.verified = create_ml_parse_reader.verified

    def set_format(self, save_format):
        if save_format == FORMAT_PASCALVOC:
            self.label_file_format = LabelFileFormat.PASCAL_VOC
            LabelFile.suffix = XML_EXT
        elif save_format == FORMAT_YOLO:
            self.label_file_format = LabelFileFormat.YOLO
            LabelFile.suffix = TXT_EXT
        elif save_format == FORMAT_CREATEML:
            self.label_file_format = LabelFileFormat.CREATE_ML
            LabelFile.suffix = JSON_EXT
        else:
            raise ValueError('Unknown label file format.')
        self.set_dirty()

    def set_dirty(self):
        self.dirty = True
        self.actions.save.setEnabled(True)

    def set_clean(self):
        self.dirty = False
        self.actions.save.setEnabled(False)
        self.actions.create.setEnabled(True)

    def current_path(self):
        return os.path.dirname(self.file_path) if self.file_path else '.'

    def error_message(self, title, message):
        return QMessageBox.critical(self, title, '<p><b>%s</b></p>%s' % (title, message))

    def show_tutorial_dialog(self, browser='default', link=None):
        if link is None:
            link = self.screencast
        if browser.lower() == 'default':
            wb.open(link, new=2)
        else:
            wb.open(link, new=2)

    def show_default_tutorial_dialog(self):
        self.show_tutorial_dialog(browser='default')

    def show_info_dialog(self):
        from libs.__init__ import __version__
        msg = u'Name:{0} \nApp Version:{1} \nPython Info: {2} '.format(__appname__, __version__, sys.version_info)
        QMessageBox.information(self, u'Information', msg)

    def show_shortcuts_dialog(self):
        self.show_tutorial_dialog(browser='default', link='https://github.com/tzutalin/labelImg#Hotkeys')

    def toggle_paint_labels_option(self):
        for shape in self.canvas.shapes:
            shape.paint_label = self.display_label_option.isChecked()
        self.canvas.update()

    def toggle_draw_square(self):
        self.canvas.set_drawing_shape_to_square(self.draw_squares_option.isChecked())

    def counter_str(self):
        return '[{} / {}]'.format(self.cur_img_idx + 1, self.img_count)

    # (Opcional) para cargar predefined classes
    def load_predefined_classes(self, predef_classes_file):
        if os.path.exists(predef_classes_file):
            with codecs.open(predef_classes_file, 'r', 'utf8') as f:
                for line in f:
                    line = line.strip()
                    self.label_hist.append(line)


# -----------------------------------------------------------------------------
# Funciones de ayuda para crear acciones y añadirlas a menús/toolbar (reutilizadas)
# -----------------------------------------------------------------------------
def new_action(parent, text, slot=None, shortcut=None, icon=None, tip=None,
               checkable=False, enabled=True):
    action = QAction(text, parent)
    if icon is not None:
        action.setIcon(new_icon(icon))
    if shortcut is not None:
        action.setShortcut(QKeySequence(shortcut))
    if tip is not None:
        action.setToolTip(tip)
        action.setStatusTip(tip)
    if slot is not None:
        action.triggered.connect(slot)
    action.setCheckable(checkable)
    action.setEnabled(enabled)
    return action


def add_actions(widget, actions):
    for action in actions:
        if action is None:
            widget.addSeparator()
        elif isinstance(action, QAction):
            widget.addAction(action)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    widget = LabelImgWidget()
    widget.show()
    sys.exit(app.exec())
# -----------------------------------------------------------------------------
# Explicación Corta
# -----------------------------------------------------------------------------
