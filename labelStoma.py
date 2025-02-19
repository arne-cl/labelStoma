#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
The `labelSummary` module contains the PyQt5-based graphical user 
interface of the LabelStoma application, designed for the detection of 
stomata on leaf images. 

The application supports basic image manipulation features like zooming 
and scrolling, and advanced annotation features including drawing 
shapes (rectangles, squares), editing, copying, and deleting 
annotations.
It also includes functionality to automatically detect 
objects within images (specifically, stomata detection in this 
context), generate Excel reports based on annotations, and prepare 
training data for machine learning models.

Key Features:

- Load images individually or in bulk from a directory.
- Support for Pascal VOC and YOLO annotation formats.
- Drawing and editing of bounding boxes with support for square drawing mode.
- Verification mode to mark images as verified for quality control.
- Recent files menu for quick access to previously opened images or projects.
- Predefined classes for quick annotation.
- Automatic stoma detection using YOLO model
- Excel report generation for analysis
- Generation of training files for model training
"""

import codecs
import os.path
import platform
import sys
import subprocess
from PyQt5 import QtWidgets

from functools import partial

try:
    from PyQt5.QtGui import *
    from PyQt5.QtCore import *
    from PyQt5.QtWidgets import *
    from PyQt5 import QtGui, QtCore
except ImportError:
    # needed for py3+qt4
    # Ref:
    # http://pyqt.sourceforge.net/Docs/PyQt4/incompatible_apis.html
    # http://stackoverflow.com/questions/21217399/pyqt4-qtcore-qvariant-object-instead-of-a-string
    if sys.version_info.major >= 3:
        import sip

        sip.setapi('QVariant', 2)


# Add internal libs
from libs.constants import *
from libs.utils import *
from libs.settings import Settings
from libs.shape import Shape, DEFAULT_LINE_COLOR, DEFAULT_FILL_COLOR
from libs.stringBundle import StringBundle
from libs.canvas import Canvas
from libs.zoomWidget import ZoomWidget
from libs.labelDialog import LabelDialog
from libs.excelDialog import ExcelDialog
from libs.prueba import Ui_Dialog
from libs.colorDialog import ColorDialog
from libs.labelFile import LabelFile, LabelFileError
from libs.toolBar import ToolBar
from libs.pascal_voc_io import PascalVocReader
from libs.pascal_voc_io import XML_EXT
from libs.yolo_io import YoloReader
from libs.yolo_io import TXT_EXT
from libs.ustr import ustr
from libs.version import __version__
from libs.hashableQListWidgetItem import HashableQListWidgetItem
from predict import detectStoma
from predict.generateExcel import generaExcel
import notebooks.notebookmenu
import notebooks.notebookYolo
import notebooks.mainModel
import predict.selectPesos
import libs.resources
__appname__ = 'labelStoma'


class WindowMixin(object):
    def menu(self, title, actions=None):
        """Creates a menu in the menu bar with the given title and actions."""
        menu = self.menuBar().addMenu(title)
        if actions:
            addActions(menu, actions)
        return menu

    def toolbar(self, title, actions=None):
        """Creates a toolbar in the application with the given title and actions."""
        toolbar = ToolBar(title)
        toolbar.setObjectName(u'%sToolBar' % title)
        toolbar.setOrientation(Qt.Vertical)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        if actions:
            addActions(toolbar, actions)
        self.addToolBar(Qt.LeftToolBarArea, toolbar)
        return toolbar


class MainWindow(QMainWindow, WindowMixin):
    FIT_WINDOW, FIT_WIDTH, MANUAL_ZOOM = list(range(3))
    shapeSize = None

    def __init__(self, defaultFilename=None, defaultPrefdefClassFile=None, defaultSaveDir=None):
        """Initialize the main window, load settings, and set up UI components."""
        super(MainWindow, self).__init__()
        self.setWindowTitle(__appname__)

        # Load setting in the main thread
        self.settings = Settings()
        self.settings.load()
        settings = self.settings

        # Load string bundle for i18n
        self.stringBundle = StringBundle.getBundle()
        getStr = lambda strId: self.stringBundle.getString(strId)

        # Save as Pascal voc xml
        self.defaultSaveDir = defaultSaveDir
        self.usingPascalVocFormat = True
        self.usingYoloFormat = False

        # For loading all image under a directory
        self.mImgList = []
        self.dirname = None
        self.labelHist = []
        self.lastOpenDir = None

        # Whether we need to save or not.
        self.dirty = False

        self._noSelectionSlot = False
        self._beginner = True
        self.screencastViewer = self.getAvailableScreencastViewer()
        self.screencast = "https://youtu.be/p0nR2YsCY_U"

        # Load predefined classes to the list
        self.loadPredefinedClasses(defaultPrefdefClassFile)
        # -----------------------------------------------------------------

        # Main widgets and related state.
        self.labelDialog = LabelDialog(parent=self, listItem=self.labelHist)
        self.excelDialog = ExcelDialog(parent=self, listItem=None)
        self.itemsToShapes = {}
        self.shapesToItems = {}
        self.prevLabelText = ''

        # -----------------------------------------------------------------
        # Jonathan. Comienza creando el elemento que contiene la lista de
        # las anotaciones (lo que aparece arriba a la derecha)
        # -----------------------------------------------------------------
        # Crea primero un layout donde irá añadiendo cosas.
        listLayout = QVBoxLayout()
        listLayout.setContentsMargins(0, 0, 0, 0)

        # De aquí hay muchas cosas que creo que se pueden eliminar.
        # Crea un checkbox para la etiqueta por defecto
        # Si queremos que use siempre la misma hay que modificar el método
        # newshape para que no pregunte. Como vamos a tener dos etiquetas
        # estoma y region, modificaría el método newshape para que tome
        # un valor adicional que sea la etiqueta.
        self.useDefaultLabelCheckbox = QCheckBox(getStr('useDefaultLabel'))
        self.useDefaultLabelCheckbox.setChecked(False)
        self.defaultLabelTextLine = QLineEdit()
        useDefaultLabelQHBoxLayout = QHBoxLayout()
        useDefaultLabelQHBoxLayout.addWidget(self.useDefaultLabelCheckbox)
        useDefaultLabelQHBoxLayout.addWidget(self.defaultLabelTextLine)
        useDefaultLabelContainer = QWidget()
        useDefaultLabelContainer.setLayout(useDefaultLabelQHBoxLayout)

        # Crea un widget para la opción anotación dificil. Creo que se puede
        # eliminar. Nada más que hay que ir en cascada, y tener en cuenta cuando
        # están marcados.
        self.diffcButton = QCheckBox(getStr('useDifficult'))
        self.diffcButton.setChecked(False)
        self.diffcButton.stateChanged.connect(self.btnstate)
        self.editButton = QToolButton()
        self.editButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        # Importante.
        # Añade los elementos a la lista. Comentando estas tres líneas queda más
        # limpio, y solo aparece la lista de anotaciones.
        # listLayout.addWidget(self.editButton)
        # listLayout.addWidget(self.diffcButton)
        # listLayout.addWidget(useDefaultLabelContainer)

        # Create and add a widget for showing current label items
        self.labelList = QListWidget()
        labelListContainer = QWidget()
        labelListContainer.setLayout(listLayout)
        self.labelList.itemActivated.connect(self.labelSelectionChanged)
        self.labelList.itemSelectionChanged.connect(self.labelSelectionChanged)
        self.labelList.itemDoubleClicked.connect(self.editLabel)
        # Connect to itemChanged to detect checkbox changes.
        self.labelList.itemChanged.connect(self.labelItemChanged)
        listLayout.addWidget(self.labelList)

        self.dock = QDockWidget(getStr('boxLabelText'), self)
        self.dock.setObjectName(getStr('labels'))
        self.dock.setWidget(labelListContainer)

        # -----------------------------------------------------------------
        # Jonathan. A continuación se crea la lista de ficheros. (lo que
        # aparece abajo a la derecha). Realmente es un layout que tiene una
        # lista.
        # -----------------------------------------------------------------
        self.fileListWidget = QListWidget()
        self.fileListWidget.itemDoubleClicked.connect(self.fileitemDoubleClicked)
        filelistLayout = QVBoxLayout()
        filelistLayout.setContentsMargins(0, 0, 0, 0)
        filelistLayout.addWidget(self.fileListWidget)
        fileListContainer = QWidget()
        fileListContainer.setLayout(filelistLayout)
        self.filedock = QDockWidget(getStr('fileList'), self)
        self.filedock.setObjectName(getStr('files'))
        self.filedock.setWidget(fileListContainer)

        # -----------------------------------------------------------------
        # Jonathan. A continuación se crea la zona central que va a ser la
        # encargada de gestionar la imagen. Esto no hay que tocar nada.
        # -----------------------------------------------------------------
        self.zoomWidget = ZoomWidget()
        self.colorDialog = ColorDialog(parent=self)

        self.canvas = Canvas(parent=self)
        self.canvas.zoomRequest.connect(self.zoomRequest)
        self.canvas.setDrawingShapeToSquare(settings.get(SETTING_DRAW_SQUARE, False))

        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setWidgetResizable(True)
        self.scrollBars = {
            Qt.Vertical: scroll.verticalScrollBar(),
            Qt.Horizontal: scroll.horizontalScrollBar()
        }
        self.scrollArea = scroll
        self.canvas.scrollRequest.connect(self.scrollRequest)

        self.canvas.newShape.connect(self.newShape)
        self.canvas.shapeMoved.connect(self.setDirty)
        self.canvas.selectionChanged.connect(self.shapeSelectionChanged)
        self.canvas.drawingPolygon.connect(self.toggleDrawingSensitive)

        self.setCentralWidget(scroll)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.filedock)
        self.filedock.setFeatures(QDockWidget.DockWidgetFloatable)

        self.dockFeatures = QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetFloatable
        self.dock.setFeatures(self.dock.features() ^ self.dockFeatures)

        # ******************************************************************
        # A partir de aquí, empieza código a modificar.
        # ******************************************************************

        # -----------------------------------------------------------------
        # Jonathan. A continuación se definen las acciones que van a incluir
        # los distintos menús. Yo aquí no tocaría nada, sino que añadiría al
        # final las nuestras.
        # -----------------------------------------------------------------
        action = partial(newAction, self)
        quit = action(getStr('quit'), self.close,
                      'Ctrl+q', 'quit', getStr('quitApp'))
        open = action(getStr('openFile'), self.openFile,
                      'Ctrl+o', 'file', getStr('openFileDetail'))
        #QKeySequence.Open
        opendir = action(getStr('openDir'), self.openDirDialog,
                         'Ctrl+u', 'open', getStr('openDir'))

        changeSavedir = action(getStr('changeSaveDir'), self.changeSavedirDialog,
                               'Ctrl+r', 'open', getStr('changeSavedAnnotationDir'))

        openAnnotation = action(getStr('openAnnotation'), self.openAnnotationDialog,
                                'Ctrl+Shift+N', 'open', getStr('openAnnotationDetail'))

        openNextImg = action(getStr('nextImg'), self.openNextImg,
                             QKeySequence.MoveToNextChar, 'next', getStr('nextImgDetail'))

        openPrevImg = action(getStr('prevImg'), self.openPrevImg,
                             QKeySequence.MoveToPreviousChar, 'prev', getStr('prevImgDetail'))

        verify = action(getStr('verifyImg'), self.verifyImg,
                        'space', 'verify', getStr('verifyImgDetail'))

        detect = action('Detect stoma and save', self.detectStoma,
                        'z', 'images', getStr('saveAsDetail'), enabled=False)
        excel = action('Generate Excel', self.generarExcel,
                       'e', 'excel', getStr('saveAsDetail'), enabled=False)
        self.editButton.setDefaultAction(excel)
        trainModel = action('Generate training files', self.trainModel,
                            't', 'trainModel', 'Generate notebooks for training', enabled=False)
        save = action(getStr('save'), self.saveFile,
                      'Ctrl+s', 'save', getStr('saveDetail'), enabled=False)

        save_format = action('&PascalVOC', self.change_format,
                             'Ctrl+', 'format_voc', getStr('changeSaveFormat'), enabled=True)

        saveAs = action(getStr('saveAs'), self.saveFileAs,
                        'Ctrl+Shift+S', 'save-as', getStr('saveAsDetail'), enabled=False)

        close = action(getStr('closeCur'), self.closeFile, 'Ctrl+W', 'close', getStr('closeCurDetail'))

        resetAll = action(getStr('resetAll'), self.resetAll, None, 'resetall', getStr('resetAllDetail'))

        color1 = action(getStr('boxLineColor'), self.chooseColor1,
                        'Ctrl+L', 'color_line', getStr('boxLineColorDetail'))

        createMode = action('Add stoma', self.setCreateMode,
                            'w', 'new', getStr('crtBoxDetail'), enabled=False)
        editMode = action('&Edit RectBox', self.setEditMode,
                          'Ctrl+J', 'edit', u'Move and edit Boxs', enabled=False)

        create = action(getStr('crtBox'), self.createShape,
                        'r', 'new', getStr('crtBoxDetail'), enabled=False)

        # Importante. Acción añadida para añadir regiones.
        createRegion = action('Add surface', self.createShapeRegion,
                              'w', 'new', getStr('crtBoxDetail'), enabled=False)

        createScale = action('Add scale', self.createShapeScale,
                              'l', 'regla', getStr('crtBoxDetail'), enabled=False)

        delete = action(getStr('delBox'), self.deleteSelectedShape,
                        'Delete', 'delete', getStr('delBoxDetail'), enabled=False)
        copy = action(getStr('dupBox'), self.copySelectedShape,
                      'Ctrl+D', 'copy', getStr('dupBoxDetail'),
                      enabled=False)

        advancedMode = action(getStr('advancedMode'), self.toggleAdvancedMode,
                              'Ctrl+Shift+A', 'expert', getStr('advancedModeDetail'),
                              checkable=True)

        hideAll = action('&Hide\nRectBox', partial(self.togglePolygons, False),
                         'Ctrl+H', 'hide', getStr('hideAllBoxDetail'),
                         enabled=False)
        showAll = action('&Show\nRectBox', partial(self.togglePolygons, True),
                         'Ctrl+A', 'hide', getStr('showAllBoxDetail'),
                         enabled=False)

        help = action(getStr('tutorial'), self.showTutorialDialog, None, 'help', getStr('tutorialDetail'))
        showInfo = action(getStr('info'), self.showInfoDialog, None, 'help', getStr('info'))

        zoom = QWidgetAction(self)
        zoom.setDefaultWidget(self.zoomWidget)
        self.zoomWidget.setWhatsThis(
            u"Zoom in or out of the image. Also accessible with"
            " %s and %s from the canvas." % (fmtShortcut("Ctrl+[-+]"),
                                             fmtShortcut("Ctrl+Wheel")))
        self.zoomWidget.setEnabled(False)

        zoomIn = action(getStr('zoomin'), partial(self.addZoom, 10),
                        'Ctrl++', 'zoom-in', getStr('zoominDetail'), enabled=False)
        zoomOut = action(getStr('zoomout'), partial(self.addZoom, -10),
                         'Ctrl+-', 'zoom-out', getStr('zoomoutDetail'), enabled=False)
        zoomOrg = action(getStr('originalsize'), partial(self.setZoom, 100),
                         'Ctrl+=', 'zoom', getStr('originalsizeDetail'), enabled=False)
        fitWindow = action(getStr('fitWin'), self.setFitWindow,
                           'Ctrl+F', 'fit-window', getStr('fitWinDetail'),
                           checkable=True, enabled=False)
        fitWidth = action(getStr('fitWidth'), self.setFitWidth,
                          'Ctrl+Shift+F', 'fit-width', getStr('fitWidthDetail'),
                          checkable=True, enabled=False)
        # Group zoom controls into a list for easier toggling.
        zoomActions = (self.zoomWidget, zoomIn, zoomOut,
                       zoomOrg, fitWindow, fitWidth)
        self.zoomMode = self.MANUAL_ZOOM
        self.scalers = {
            self.FIT_WINDOW: self.scaleFitWindow,
            self.FIT_WIDTH: self.scaleFitWidth,
            # Set to one to scale to 100% when loading files.
            self.MANUAL_ZOOM: lambda: 1,
        }

        edit = action(getStr('editLabel'), self.editLabel,
                      'Ctrl+E', 'edit', getStr('editLabelDetail'),
                      enabled=False)
        self.editButton.setDefaultAction(edit)

        shapeLineColor = action(getStr('shapeLineColor'), self.chshapeLineColor,
                                icon='color_line', tip=getStr('shapeLineColorDetail'),
                                enabled=False)
        shapeFillColor = action(getStr('shapeFillColor'), self.chshapeFillColor,
                                icon='color', tip=getStr('shapeFillColorDetail'),
                                enabled=False)

        labels = self.dock.toggleViewAction()
        labels.setText(getStr('showHide'))
        labels.setShortcut('Ctrl+Shift+L')

        # Lavel list context menu.
        labelMenu = QMenu()
        addActions(labelMenu, (edit, delete))
        self.labelList.setContextMenuPolicy(Qt.CustomContextMenu)
        self.labelList.customContextMenuRequested.connect(
            self.popLabelListMenu)

        # Draw squares/rectangles
        self.drawSquaresOption = QAction('Draw Squares', self)
        self.drawSquaresOption.setShortcut('Ctrl+Shift+R')
        self.drawSquaresOption.setCheckable(True)
        self.drawSquaresOption.setChecked(settings.get(SETTING_DRAW_SQUARE, False))
        self.drawSquaresOption.triggered.connect(self.toogleDrawSquare)

        # -----------------------------------------------------------------
        # Jonathan. Todas las acciones que se han definido deben añadirse
        # al siguiente diccinoario para poder ser utilizadas luego, yo
        # he añadido lo de createRegion.
        # -----------------------------------------------------------------

        self.actions = struct(save=save, save_format=save_format, saveAs=saveAs, open=open, close=close,
                              resetAll=resetAll,
                              lineColor=color1, create=create, createRegion=createRegion, createScale=createScale,delete=delete, edit=edit,
                              copy=copy, detect=detect, excel=excel, trainModel=trainModel,
                              createMode=createMode, editMode=editMode, advancedMode=advancedMode,
                              shapeLineColor=shapeLineColor, shapeFillColor=shapeFillColor,
                              zoom=zoom, zoomIn=zoomIn, zoomOut=zoomOut, zoomOrg=zoomOrg,
                              fitWindow=fitWindow, fitWidth=fitWidth,
                              zoomActions=zoomActions,
                              fileMenuActions=(
                                  open, opendir, save, saveAs, close, resetAll, quit),
                              beginner=(), advanced=(),
                              editMenu=(edit, copy, delete,
                                        None, color1, self.drawSquaresOption),
                              beginnerContext=(create, edit, copy, delete),
                              advancedContext=(createMode, editMode, edit, copy,
                                               delete, shapeLineColor, shapeFillColor),
                              onLoadActive=(
                                  close, create, createMode, editMode),
                              onShapesPresent=(saveAs, hideAll, showAll))

        # -----------------------------------------------------------------
        # Jonathan. Aquí se va a definir cada uno de los menús.
        # Me he cargado el menú Edit pero manteniendo la barra de
        # herramientas lateral
        # -----------------------------------------------------------------

        self.menus = struct(
            file=self.menu('&File'),
            # edit=self.menu('&Edit'),
            #view=self.menu('&View'),
            stoma = self.menu('&Edit Stoma'),
            help=self.menu('&Help'),
            recentFiles=QMenu('Open &Recent'),
            labelList=labelMenu)

        # toolbar = ToolBar("prueba")
        # toolbar.setObjectName(u'ToolBar2')
        # addActions(toolbar, (save,save_format))
        # toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        # self.addToolBar(Qt.BottomToolBarArea, toolbar)

        # Auto saving : Enable auto saving if pressing next
        self.autoSaving = QAction(getStr('autoSaveMode'), self)
        self.autoSaving.setCheckable(True)

        # Jónathan. Al activar el autosave mode, al abrir un directorio te pide que
        # indiques el directorio donde se van a guardar las imágenes. Se podría cambiar para
        # que fuera el mismo donde están dichas imágenes.

        # Jónathan. Definición menú view
        # Como hay botones especiales que necesitan checkbox se definen de esta manera.
        # Sino bastaría con añadir las acciones al menú.
        self.autoSaving.setChecked(settings.get(SETTING_AUTO_SAVE, True))



        # Sync single class mode from PR#106
        self.singleClassMode = QAction(getStr('singleClsMode'), self)
        self.singleClassMode.setShortcut("Ctrl+Shift+S")
        self.singleClassMode.setCheckable(True)
        self.singleClassMode.setChecked(settings.get(SETTING_SINGLE_CLASS, False))
        self.lastLabel = None
        # Add option to enable/disable labels being displayed at the top of bounding boxes
        self.displayLabelOption = QAction(getStr('displayLabel'), self)
        self.displayLabelOption.setShortcut("Ctrl+Shift+P")
        self.displayLabelOption.setCheckable(True)
        self.displayLabelOption.setChecked(settings.get(SETTING_PAINT_LABEL, False))
        self.displayLabelOption.triggered.connect(self.togglePaintLabelsOption)
        # Jónathan. Del menú view he quitado lo de advanced mode, para que no se pueda cambiar.
        # addActions(self.menus.view, (
        #     self.autoSaving,
        #     self.singleClassMode,
        #     self.displayLabelOption,
        #     labels, advancedMode, None,
        #     hideAll, showAll, None,
        #     zoomIn, zoomOut, zoomOrg, None,
        #     fitWindow, fitWidth))

        # Jónathan. Definición menú file
        addActions(self.menus.file,
                   (open, opendir, quit))
        # Jónathan. Definición menú help
        addActions(self.menus.help, (help, showInfo))

        self.menus.file.aboutToShow.connect(self.updateFileMenu)

        # Definición del menú edit stoma
        addActions(self.menus.stoma, (create, createRegion, detect, createScale, excel, trainModel,close))

        # Custom context menu for the canvas widget:
        addActions(self.canvas.menus[0], self.actions.beginnerContext)
        addActions(self.canvas.menus[1], (
            action('&Copy here', self.copyShape),
            action('&Move here', self.moveShape)))

        # -----------------------------------------------------------------
        # Jónathan. Se define el toolbar.
        # -----------------------------------------------------------------
        self.tools = self.toolbar('Tools')
        # Jónathan. Las acciones que se van añadir al toolbar son las que aparecen a continuación.
        # Dependiendo del modo se muestran unas u otras, pero en nuestro caso solo va a haber modo
        # beginner.
        self.actions.beginner = (
            open, opendir, openNextImg, openPrevImg,None, save,  detect,excel,trainModel,None,create, createRegion, createScale, delete)

        # Como solo hay modo beginner esto se puede quedar como una lista vacía.
        self.actions.advanced = ()

        # ******************************************************************
        # Aquí termina código a modificar. Salvo luego las nuevas funciones
        # que se definan.
        # ******************************************************************

        # -----------------------------------------------------------------
        # Jónathan. Más parámetros de cofiguración. No hace falta tocarlos.
        # -----------------------------------------------------------------
        self.statusBar().showMessage('%s started.' % __appname__)
        self.statusBar().show()
        self.image = QImage()
        self.filePath = ustr(defaultFilename)
        self.recentFiles = []
        self.maxRecent = 7
        self.lineColor = None
        self.fillColor = None
        self.zoom_level = 100
        self.fit_window = False
        # Add Chris
        self.difficult = False

        ## Fix the compatible issue for qt4 and qt5. Convert the QStringList to python list
        if settings.get(SETTING_RECENT_FILES):
            if have_qstring():
                recentFileQStringList = settings.get(SETTING_RECENT_FILES)
                self.recentFiles = [ustr(i) for i in recentFileQStringList]
            else:
                self.recentFiles = recentFileQStringList = settings.get(SETTING_RECENT_FILES)

        size = settings.get(SETTING_WIN_SIZE, QSize(600, 500))
        position = QPoint(0, 0)
        saved_position = settings.get(SETTING_WIN_POSE, position)
        # Fix the multiple monitors issue
        for i in range(QApplication.desktop().screenCount()):
            if QApplication.desktop().availableGeometry(i).contains(saved_position):
                position = saved_position
                break
        self.resize(size)
        self.move(position)
        saveDir = ustr(settings.get(SETTING_SAVE_DIR, None))
        self.lastOpenDir = ustr(settings.get(SETTING_LAST_OPEN_DIR, None))
        if self.defaultSaveDir is None and saveDir is not None and os.path.exists(saveDir):
            self.defaultSaveDir = saveDir
            self.statusBar().showMessage('%s started. Annotation will be saved to %s' %
                                         (__appname__, self.defaultSaveDir))
            self.statusBar().show()

        self.restoreState(settings.get(SETTING_WIN_STATE, QByteArray()))
        Shape.line_color = self.lineColor = QColor(settings.get(SETTING_LINE_COLOR, DEFAULT_LINE_COLOR))
        Shape.fill_color = self.fillColor = QColor(settings.get(SETTING_FILL_COLOR, DEFAULT_FILL_COLOR))
        self.canvas.setDrawingColor(self.lineColor)
        # Add chris
        Shape.difficult = self.difficult

        def xbool(x):
            if isinstance(x, QVariant):
                return x.toBool()
            return bool(x)

        if xbool(settings.get(SETTING_ADVANCE_MODE, False)):
            self.actions.advancedMode.setChecked(True)
            self.toggleAdvancedMode()

        # Populate the File menu dynamically.
        self.updateFileMenu()

        # Since loading the file may take some time, make sure it runs in the background.
        if self.filePath and os.path.isdir(self.filePath):
            self.queueEvent(partial(self.importDirImages, self.filePath or ""))
        elif self.filePath:
            self.queueEvent(partial(self.loadFile, self.filePath or ""))

        # Callbacks:
        self.zoomWidget.valueChanged.connect(self.paintCanvas)

        self.populateModeActions()

        # Display cursor coordinates at the right of status bar
        self.labelCoordinates = QLabel('')
        self.statusBar().addPermanentWidget(self.labelCoordinates)

        # Open Dir if deafult file
        if self.filePath and os.path.isdir(self.filePath):
            self.openDirDialog(dirpath=self.filePath)

    def keyReleaseEvent(self, event):
        """Event handler for key release events, specifically to stop drawing squares when Ctrl is released."""
        if event.key() == Qt.Key_Control:
            self.canvas.setDrawingShapeToSquare(False)

    def keyPressEvent(self, event):
        """Event handler for key press events, specifically to start drawing squares when Ctrl is pressed."""
        if event.key() == Qt.Key_Control:
            self.canvas.setDrawingShapeToSquare(True)

    def set_format(self, save_format):
        """Sets the format for saving label files (PascalVOC or YOLO)."""
        if save_format == FORMAT_PASCALVOC:
            self.actions.save_format.setText(FORMAT_PASCALVOC)
            self.actions.save_format.setIcon(newIcon("format_voc"))
            self.usingPascalVocFormat = True
            self.usingYoloFormat = False
            LabelFile.suffix = XML_EXT

        elif save_format == FORMAT_YOLO:
            self.actions.save_format.setText(FORMAT_YOLO)
            self.actions.save_format.setIcon(newIcon("format_yolo"))
            self.usingPascalVocFormat = False
            self.usingYoloFormat = True
            LabelFile.suffix = TXT_EXT

    def change_format(self):
        """Changes the current format for saving label files between PascalVOC and YOLO."""
        if self.usingPascalVocFormat:
            self.set_format(FORMAT_YOLO)
        elif self.usingYoloFormat:
            self.set_format(FORMAT_PASCALVOC)

    def noShapes(self):
        """Checks if there are no shapes (labels) present."""
        return not self.itemsToShapes

    def toggleAdvancedMode(self, value=True):
        """Toggles the UI between beginner and advanced mode."""
        self._beginner = not value
        self.canvas.setEditing(True)
        self.populateModeActions()
        self.editButton.setVisible(not value)
        if value:
            self.actions.createMode.setEnabled(True)
            self.actions.editMode.setEnabled(False)
            self.dock.setFeatures(self.dock.features() | self.dockFeatures)
        else:
            self.dock.setFeatures(self.dock.features() ^ self.dockFeatures)

    def populateModeActions(self):
        """Updates the UI actions based on the current mode (beginner or advanced)."""
        if self.beginner():
            tool, menu = self.actions.beginner, self.actions.beginnerContext
        else:
            tool, menu = self.actions.advanced, self.actions.advancedContext
        self.tools.clear()
        addActions(self.tools, tool)
        self.canvas.menus[0].clear()
        addActions(self.canvas.menus[0], menu)

    def setBeginner(self):
        """Sets the UI to beginner mode."""
        self.tools.clear()
        addActions(self.tools, self.actions.beginner)

    def setAdvanced(self):
        """Sets the UI to advanced mode."""
        self.tools.clear()
        addActions(self.tools, self.actions.advanced)

    def setDirty(self):
        """Marks the current project as having unsaved changes."""
        self.dirty = True
        self.actions.save.setEnabled(False)

    def setClean(self):
        """Marks the current project as having all changes saved."""
        self.dirty = False
        self.actions.save.setEnabled(False)
        self.actions.create.setEnabled(True)
        # You need to enable the createRegion button when you open an image.
        self.actions.createRegion.setEnabled(True)
        self.actions.createScale.setEnabled(True)
        self.actions.detect.setEnabled(True)
        self.actions.excel.setEnabled(True)
        self.actions.trainModel.setEnabled(True)

    def toggleActions(self, value=True):
        """Enables or disables actions based on whether an image is loaded."""
        for z in self.actions.zoomActions:
            z.setEnabled(value)
        for action in self.actions.onLoadActive:
            action.setEnabled(value)

    def queueEvent(self, function):
        """Queues an event (function call) to be executed."""
        QTimer.singleShot(0, function)

    def status(self, message, delay=5000):
        """Displays a message in the status bar."""
        self.statusBar().showMessage(message, delay)

    def resetState(self):
        """Resets the application state (e.g., clears shapes and selected files)."""
        self.itemsToShapes.clear()
        self.shapesToItems.clear()
        self.labelList.clear()
        self.filePath = None
        self.imageData = None
        self.labelFile = None
        self.canvas.resetState()
        self.labelCoordinates.clear()

    def currentItem(self):
        """Returns the currently selected label item."""
        items = self.labelList.selectedItems()
        if items:
            return items[0]
        return None

    def addRecentFile(self, filePath):
        """Adds a file to the list of recently opened files."""
        if filePath in self.recentFiles:
            self.recentFiles.remove(filePath)
        elif len(self.recentFiles) >= self.maxRecent:
            self.recentFiles.pop()
        self.recentFiles.insert(0, filePath)

    def beginner(self):
        """Checks if the application is in beginner mode."""
        return self._beginner

    def advanced(self):
        """Checks if the application is in advanced mode."""
        return not self.beginner()

    def getAvailableScreencastViewer(self):
        """Gets the available viewer for screencasts based on the operating system."""
        osName = platform.system()

        if osName == 'Windows':
            return ['C:\\Program Files\\Internet Explorer\\iexplore.exe']
        elif osName == 'Linux':
            return ['xdg-open']
        elif osName == 'Darwin':
            return ['open', '-a', 'Safari']

    def showTutorialDialog(self):
        """Shows a dialog with the tutorial video."""
        subprocess.Popen(self.screencastViewer + [self.screencast])

    def showInfoDialog(self):
        """Shows a dialog with application information."""
        msg = u'Name:{0} \nApp Version:{1} \n{2} '.format(__appname__, __version__, sys.version_info)
        QMessageBox.information(self, u'Information', msg)


    # We define two functions, one for adding regions and one for adding stomata.
    # The difference is the default text that sets each of them.
    def createShape(self):
        """Creates a new shape with a default label "stoma"."""
        assert self.beginner()
        self.text = 'stoma'
        self.canvas.setEditing(False)
        self.actions.create.setEnabled(False)
        self.actions.createRegion.setEnabled(False)
        self.saveFile()
        print(self.canvas.shapes[0])

    def createShapeRegion(self):
        """Creates a new shape with a default label "superficie" for regions."""
        assert self.beginner()
        self.text = 'superficie'
        self.canvas.setEditing(False)
        self.actions.create.setEnabled(False)
        self.actions.createRegion.setEnabled(False)
        self.saveFile()

    def createShapeScale(self):
        """Creates a new shape with a default label "scale" for scales."""
        assert self.beginner()
        self.text = 'scale'
        self.canvas.setEditing(False)
        self.actions.create.setEnabled(False)
        self.actions.createScale.setEnabled(False)
        # Once we have added the scale, we activate the option to generate an Excel file.
        self.actions.excel.setEnabled(True)
        self.saveFile()

    def toggleDrawingSensitive(self, drawing=True):
        """In the middle of drawing, toggling between modes should be disabled."""
        self.actions.editMode.setEnabled(not drawing)
        if not drawing and self.beginner():
            # Cancel creation.
            print('Cancel creation.')
            self.canvas.setEditing(True)
            self.canvas.restoreCursor()
            self.actions.create.setEnabled(True)
            self.actions.createRegion.setEnabled(True)

    def toggleDrawMode(self, edit=True):
        """Toggles between create and edit mode for drawing shapes."""
        self.canvas.setEditing(edit)
        self.actions.createMode.setEnabled(edit)
        self.actions.editMode.setEnabled(not edit)
        self.saveFile()

    def setCreateMode(self):
        """Sets the application to create mode for drawing new shapes."""
        assert self.advanced()
        self.toggleDrawMode(False)

    def setEditMode(self):
        """Sets the application to edit mode for modifying existing shapes."""
        assert self.advanced()
        self.toggleDrawMode(True)
        self.labelSelectionChanged()

    def updateFileMenu(self):
        """Updates the File menu, especially the recent files submenu."""
        currFilePath = self.filePath

        def exists(filename):
            return os.path.exists(filename)

        menu = self.menus.recentFiles
        menu.clear()
        files = [f for f in self.recentFiles if f !=
                 currFilePath and exists(f)]
        for i, f in enumerate(files):
            icon = newIcon('labels')
            action = QAction(
                icon, '&%d %s' % (i + 1, QFileInfo(f).fileName()), self)
            action.triggered.connect(partial(self.loadRecent, f))
            menu.addAction(action)

    def popLabelListMenu(self, point):
        """Shows the context menu for the label list."""
        self.menus.labelList.exec_(self.labelList.mapToGlobal(point))

    def editLabel(self):
        """Opens a dialog to edit the currently selected label."""
        if not self.canvas.editing():
            return
        item = self.currentItem()
        if not item:
            return
        text = self.labelDialog.popUp(item.text())
        if text is not None:
            item.setText(text)
            item.setBackground(generateColorByText(text))
            self.setDirty()

    def fileitemDoubleClicked(self, item=None):
        """Loads an image when its filename is double-clicked from the file list."""
        currIndex = self.mImgList.index(ustr(item.text()))
        if currIndex < len(self.mImgList):
            filename = self.mImgList[currIndex]
            if filename:
                self.loadFile(filename)

    def btnstate(self, item=None):
        """"Handles the state change of the "difficult" checkbox for a selected label."""
        if not self.canvas.editing():
            return

        item = self.currentItem()
        if not item:  # If not selected Item, take the first one
            item = self.labelList.item(self.labelList.count() - 1)

        difficult = self.diffcButton.isChecked()

        try:
            shape = self.itemsToShapes[item]
        except:
            pass
        # Checked and Update
        try:
            if difficult != shape.difficult:
                shape.difficult = difficult
                self.setDirty()
            else:  # User probably changed item visibility
                self.canvas.setShapeVisible(shape, item.checkState() == Qt.Checked)
        except:
            pass

    # React to canvas signals.
    def shapeSelectionChanged(self, selected=False):
        """Handles changes in shape selection within the canvas."""
        if self._noSelectionSlot:
            self._noSelectionSlot = False
        else:
            shape = self.canvas.selectedShape
            if shape:
                self.shapesToItems[shape].setSelected(True)
            else:
                self.labelList.clearSelection()
        self.actions.delete.setEnabled(selected)
        self.actions.copy.setEnabled(selected)
        self.actions.edit.setEnabled(selected)
        self.actions.shapeLineColor.setEnabled(selected)
        self.actions.shapeFillColor.setEnabled(selected)

    def addLabel(self, shape):
        """Adds a label to the label list for a given shape."""
        shape.paintLabel = self.displayLabelOption.isChecked()
        item = HashableQListWidgetItem(shape.label)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        item.setBackground(generateColorByText(shape.label))
        self.itemsToShapes[item] = shape
        self.shapesToItems[shape] = item
        self.labelList.addItem(item)
        for action in self.actions.onShapesPresent:
            action.setEnabled(True)

    def remLabel(self, shape):
        """Removes a label from the label list."""
        if shape is None:
            return
        item = self.shapesToItems[shape]
        self.labelList.takeItem(self.labelList.row(item))
        del self.shapesToItems[shape]
        del self.itemsToShapes[item]

    def loadLabels(self, shapes):
        """Loads labels (shapes) into the canvas."""
        s = []
        for label, points, line_color, fill_color, difficult in shapes:
            shape = Shape(label=label)
            for x, y in points:

                # Ensure the labels are within the bounds of the image. If not, fix them.
                x, y, snapped = self.canvas.snapPointToCanvas(x, y)
                if snapped:
                    self.setDirty()

                shape.addPoint(QPointF(x, y))
            shape.difficult = difficult
            shape.close()
            s.append(shape)

            if line_color:
                shape.line_color = QColor(*line_color)
            else:
                shape.line_color = generateColorByText(label)

            if fill_color:
                shape.fill_color = QColor(*fill_color)
            else:
                shape.fill_color = generateColorByText(label)

            self.addLabel(shape)

        self.canvas.loadShapes(s)

    def saveLabels(self, annotationFilePath):
        """Saves the current labels (shapes) to a file."""
        annotationFilePath = ustr(annotationFilePath)
        if self.labelFile is None:
            self.labelFile = LabelFile()
            self.labelFile.verified = self.canvas.verified

        def format_shape(s):
            return dict(label=s.label,
                        line_color=s.line_color.getRgb(),
                        fill_color=s.fill_color.getRgb(),
                        points=[(p.x(), p.y()) for p in s.points],
                        # add chris
                        difficult=s.difficult)

        shapes = [format_shape(shape) for shape in self.canvas.shapes]
        # Can add differrent annotation formats here
        try:
            if self.usingPascalVocFormat is True:
                if annotationFilePath[-4:].lower() != ".xml":
                    annotationFilePath += XML_EXT
                self.labelFile.savePascalVocFormat(annotationFilePath, shapes, self.filePath, self.imageData,
                                                   self.lineColor.getRgb(), self.fillColor.getRgb())
            elif self.usingYoloFormat is True:
                if annotationFilePath[-4:].lower() != ".txt":
                    annotationFilePath += TXT_EXT
                self.labelFile.saveYoloFormat(annotationFilePath, shapes, self.filePath, self.imageData, self.labelHist,
                                              self.lineColor.getRgb(), self.fillColor.getRgb())
            else:
                self.labelFile.save(annotationFilePath, shapes, self.filePath, self.imageData,
                                    self.lineColor.getRgb(), self.fillColor.getRgb())
            print('Image:{0} -> Annotation:{1}'.format(self.filePath, annotationFilePath))
            return True
        except LabelFileError as e:
            self.errorMessage(u'Error saving label data', u'<b>%s</b>' % e)
            return False

    def copySelectedShape(self):
        """Copies the currently selected shape."""
        self.addLabel(self.canvas.copySelectedShape())
        # fix copy and delete
        self.shapeSelectionChanged(True)

    def labelSelectionChanged(self):
        """Updates UI based on label selection changes in the label list."""
        item = self.currentItem()
        if item and self.canvas.editing():
            self._noSelectionSlot = True
            self.canvas.selectShape(self.itemsToShapes[item])
            shape = self.itemsToShapes[item]
            self.diffcButton.setChecked(shape.difficult)

    def labelItemChanged(self, item):
        """Handles changes to label items, such as text or visibility."""
        shape = self.itemsToShapes[item]
        label = item.text()
        if label != shape.label:
            shape.label = item.text()
            shape.line_color = generateColorByText(shape.label)
            self.setDirty()
        else:  # User probably changed item visibility
            self.canvas.setShapeVisible(shape, item.checkState() == Qt.Checked)

    def newShapeStoma(self, text='stoma'):
        """Creates a new shape with a default label "stoma"."""
        if text is not None:
            self.prevLabelText = text
            generate_color = generateColorByText(text)
            shape = self.canvas.setLastLabel(text, generate_color, generate_color)
            self.addLabel(shape)
            if self.beginner():  # Switch to edit mode.
                self.canvas.setEditing(True)
                self.actions.create.setEnabled(True)
                self.actions.createRegion.setEnabled(True)
            else:
                self.actions.editMode.setEnabled(True)
            self.setDirty()

            if text not in self.labelHist:
                self.labelHist.append(text)
        else:
            self.canvas.resetAllLines()

    def newShape(self):
        """Creates a new shape based on the last used text."""
        text = self.text
        if text is not None:
            self.prevLabelText = text
            generate_color = generateColorByText(text)
            shape = self.canvas.setLastLabel(text, generate_color, generate_color)
            self.addLabel(shape)
            if self.beginner():  # Switch to edit mode.
                self.canvas.setEditing(True)
                self.actions.create.setEnabled(True)
                self.actions.createRegion.setEnabled(True)
            else:
                self.actions.editMode.setEnabled(True)
            self.setDirty()

            if text not in self.labelHist:
                self.labelHist.append(text)
        else:
            self.canvas.resetAllLines()

    def scrollRequest(self, delta, orientation):
        """Scrolls the canvas based on user input."""
        units = - delta / (8 * 15)
        bar = self.scrollBars[orientation]
        bar.setValue(bar.value() + bar.singleStep() * units)

    def setZoom(self, value):
        """Sets the zoom level of the canvas."""
        self.actions.fitWidth.setChecked(False)
        self.actions.fitWindow.setChecked(False)
        self.zoomMode = self.MANUAL_ZOOM
        self.zoomWidget.setValue(value)

    def addZoom(self, increment=10):
        """Increments or decrements the current zoom level."""
        self.setZoom(self.zoomWidget.value() + increment)

    def zoomRequest(self, delta):
        """Handles zoom requests, such as from mouse wheel input."""
        # get the current scrollbar positions
        # calculate the percentages ~ coordinates
        h_bar = self.scrollBars[Qt.Horizontal]
        v_bar = self.scrollBars[Qt.Vertical]

        # get the current maximum, to know the difference after zooming
        h_bar_max = h_bar.maximum()
        v_bar_max = v_bar.maximum()

        # get the cursor position and canvas size
        # calculate the desired movement from 0 to 1
        # where 0 = move left
        #       1 = move right
        # up and down analogous
        cursor = QCursor()
        pos = cursor.pos()
        relative_pos = QWidget.mapFromGlobal(self, pos)

        cursor_x = relative_pos.x()
        cursor_y = relative_pos.y()

        w = self.scrollArea.width()
        h = self.scrollArea.height()

        # the scaling from 0 to 1 has some padding
        # you don't have to hit the very leftmost pixel for a maximum-left movement
        margin = 0.1
        move_x = (cursor_x - margin * w) / (w - 2 * margin * w)
        move_y = (cursor_y - margin * h) / (h - 2 * margin * h)

        # clamp the values from 0 to 1
        move_x = min(max(move_x, 0), 1)
        move_y = min(max(move_y, 0), 1)

        # zoom in
        units = delta / (8 * 15)
        scale = 10
        self.addZoom(scale * units)

        # get the difference in scrollbar values
        # this is how far we can move
        d_h_bar_max = h_bar.maximum() - h_bar_max
        d_v_bar_max = v_bar.maximum() - v_bar_max

        # get the new scrollbar values
        new_h_bar_value = h_bar.value() + move_x * d_h_bar_max
        new_v_bar_value = v_bar.value() + move_y * d_v_bar_max

        h_bar.setValue(new_h_bar_value)
        v_bar.setValue(new_v_bar_value)

    def setFitWindow(self, value=True):
        """Sets the zoom level to fit the image within the window."""
        if value:
            self.actions.fitWidth.setChecked(False)
        self.zoomMode = self.FIT_WINDOW if value else self.MANUAL_ZOOM
        self.adjustScale()

    def setFitWidth(self, value=True):
        """Sets the zoom level to fit the image width within the window."""
        if value:
            self.actions.fitWindow.setChecked(False)
        self.zoomMode = self.FIT_WIDTH if value else self.MANUAL_ZOOM
        self.adjustScale()

    def togglePolygons(self, value):
        """Shows or hides all polygons (shapes) in the canvas."""
        for item, shape in self.itemsToShapes.items():
            item.setCheckState(Qt.Checked if value else Qt.Unchecked)

    def loadFile(self, filePath=None):
        """
        Loads an image file and its associated labels into the application.
        Load the last opened file if filePath=None.
        """
        self.resetState()
        self.canvas.setEnabled(False)
        if filePath is None:
            filePath = self.settings.get(SETTING_FILENAME)

        # Make sure that filePath is a regular python string, rather than QString
        filePath = ustr(filePath)

        unicodeFilePath = ustr(filePath)
        # Tzutalin 20160906 : Add file list and dock to move faster
        # Highlight the file item
        if unicodeFilePath and self.fileListWidget.count() > 0:
            index = self.mImgList.index(unicodeFilePath)
            fileWidgetItem = self.fileListWidget.item(index)
            fileWidgetItem.setSelected(True)

        if unicodeFilePath and os.path.exists(unicodeFilePath):
            if LabelFile.isLabelFile(unicodeFilePath):
                try:
                    self.labelFile = LabelFile(unicodeFilePath)
                except LabelFileError as e:
                    self.errorMessage(u'Error opening file',
                                      (u"<p><b>%s</b></p>"
                                       u"<p>Make sure <i>%s</i> is a valid label file.")
                                      % (e, unicodeFilePath))
                    self.status("Error reading %s" % unicodeFilePath)
                    return False
                self.imageData = self.labelFile.imageData
                self.lineColor = QColor(*self.labelFile.lineColor)
                self.fillColor = QColor(*self.labelFile.fillColor)
                self.canvas.verified = self.labelFile.verified
            else:
                # Load image:
                # read data first and store for saving into label file.
                self.imageData = read(unicodeFilePath, None)
                self.labelFile = None
                self.canvas.verified = False

            image = QImage.fromData(self.imageData)
            if image.isNull():
                self.errorMessage(u'Error opening file',
                                  u"<p>Make sure <i>%s</i> is a valid image file." % unicodeFilePath)
                self.status("Error reading %s" % unicodeFilePath)
                return False
            self.status("Loaded %s" % os.path.basename(unicodeFilePath))
            self.image = image
            self.filePath = unicodeFilePath
            self.canvas.loadPixmap(QPixmap.fromImage(image))
            if self.labelFile:
                self.loadLabels(self.labelFile.shapes)
            self.setClean()
            self.canvas.setEnabled(True)
            self.adjustScale(initial=True)
            self.paintCanvas()
            self.addRecentFile(self.filePath)
            self.toggleActions(True)

            # Label xml file and show bound box according to its filename
            # if self.usingPascalVocFormat is True:
            if self.defaultSaveDir is not None:
                basename = os.path.basename(
                    os.path.splitext(self.filePath)[0])
                xmlPath = os.path.join(self.defaultSaveDir, basename + XML_EXT)
                txtPath = os.path.join(self.defaultSaveDir, basename + TXT_EXT)

                """Annotation file priority:
                PascalXML > YOLO
                """
                if os.path.isfile(xmlPath):
                    self.loadPascalXMLByFilename(xmlPath)
                elif os.path.isfile(txtPath):
                    self.loadYOLOTXTByFilename(txtPath)
            else:
                xmlPath = os.path.splitext(filePath)[0] + XML_EXT
                txtPath = os.path.splitext(filePath)[0] + TXT_EXT
                if os.path.isfile(xmlPath):
                    self.loadPascalXMLByFilename(xmlPath)
                elif os.path.isfile(txtPath):
                    self.loadYOLOTXTByFilename(txtPath)

            self.setWindowTitle(__appname__ + ' ' + filePath)

            # Default : select last item if there is at least one item
            if self.labelList.count():
                self.labelList.setCurrentItem(self.labelList.item(self.labelList.count() - 1))
                self.labelList.item(self.labelList.count() - 1).setSelected(True)

            self.canvas.setFocus(True)
            return True
        return False

    def resizeEvent(self, event):
        """Handles window resize events to adjust the canvas size and zoom level."""
        if self.canvas and not self.image.isNull() \
                and self.zoomMode != self.MANUAL_ZOOM:
            self.adjustScale()
        super(MainWindow, self).resizeEvent(event)

    def paintCanvas(self):
        """Updates the canvas display based on the current zoom level and image."""
        assert not self.image.isNull(), "cannot paint null image"
        self.canvas.scale = 0.01 * self.zoomWidget.value()
        self.canvas.adjustSize()
        self.canvas.update()

    def adjustScale(self, initial=False):
        """Adjusts the zoom level of the canvas to fit the window or image width."""
        value = self.scalers[self.FIT_WINDOW if initial else self.zoomMode]()
        self.zoomWidget.setValue(int(100 * value))

    def scaleFitWindow(self):
        """Figure out the size of the pixmap in order to fit the main widget."""
        e = 2.0  # So that no scrollbars are generated.
        w1 = self.centralWidget().width() - e
        h1 = self.centralWidget().height() - e
        a1 = w1 / h1
        # Calculate a new scale value based on the pixmap's aspect ratio.
        w2 = self.canvas.pixmap.width() - 0.0
        h2 = self.canvas.pixmap.height() - 0.0
        a2 = w2 / h2
        return w1 / w2 if a2 >= a1 else h1 / h2

    def scaleFitWidth(self):
        """Scales the image to fit the width of the canvas while maintaining the aspect ratio."""
        # The epsilon does not seem to work too well here.
        w = self.centralWidget().width() - 2.0
        return w / self.canvas.pixmap.width()

    def closeEvent(self, event):
        """Handles the event when the application window is closed, prompting for unsaved changes."""
        if not self.mayContinue():
            event.ignore()
        settings = self.settings
        # If it loads images from dir, don't load it at the begining
        if self.dirname is None:
            settings[SETTING_FILENAME] = self.filePath if self.filePath else ''
        else:
            settings[SETTING_FILENAME] = ''

        settings[SETTING_WIN_SIZE] = self.size()
        settings[SETTING_WIN_POSE] = self.pos()
        settings[SETTING_WIN_STATE] = self.saveState()
        settings[SETTING_LINE_COLOR] = self.lineColor
        settings[SETTING_FILL_COLOR] = self.fillColor
        settings[SETTING_RECENT_FILES] = self.recentFiles
        settings[SETTING_ADVANCE_MODE] = not self._beginner
        if self.defaultSaveDir and os.path.exists(self.defaultSaveDir):
            settings[SETTING_SAVE_DIR] = ustr(self.defaultSaveDir)
        else:
            settings[SETTING_SAVE_DIR] = ''

        if self.lastOpenDir and os.path.exists(self.lastOpenDir):
            settings[SETTING_LAST_OPEN_DIR] = self.lastOpenDir
        else:
            settings[SETTING_LAST_OPEN_DIR] = ''

        settings[SETTING_AUTO_SAVE] = self.autoSaving.isChecked()
        settings[SETTING_SINGLE_CLASS] = self.singleClassMode.isChecked()
        settings[SETTING_PAINT_LABEL] = self.displayLabelOption.isChecked()
        settings[SETTING_DRAW_SQUARE] = self.drawSquaresOption.isChecked()
        settings.save()

    def loadRecent(self, filename):
        """Loads a recently opened file."""
        if self.mayContinue():
            self.loadFile(filename)

    def scanAllImages(self, folderPath):
        """Scans a directory for all images that can be opened."""
        extensions = ['.%s' % fmt.data().decode("ascii").lower() for fmt in QImageReader.supportedImageFormats()]
        images = []

        for root, dirs, files in os.walk(folderPath):
            for file in files:
                if file.lower().endswith(tuple(extensions)):
                    relativePath = os.path.join(root, file)
                    path = ustr(os.path.abspath(relativePath))
                    images.append(path)
        natural_sort(images, key=lambda x: x.lower())
        return images

    def changeSavedirDialog(self, _value=False):
        """Opens a dialog to change the directory where annotations are saved."""
        if self.defaultSaveDir is not None:
            path = ustr(self.defaultSaveDir)
        else:
            path = '.'

        dirpath = ustr(QFileDialog.getExistingDirectory(self,
                                                        '%s - Save annotations to the directory' % __appname__, path,
                                                        QFileDialog.ShowDirsOnly
                                                        | QFileDialog.DontResolveSymlinks))

        if dirpath is not None and len(dirpath) > 1:
            self.defaultSaveDir = dirpath

        self.statusBar().showMessage('%s . Annotation will be saved to %s' %
                                     ('Change saved folder', self.defaultSaveDir))
        self.statusBar().show()

    def openAnnotationDialog(self, _value=False):
        """Opens a dialog to load an annotation file."""
        if self.filePath is None:
            self.statusBar().showMessage('Please select image first')
            self.statusBar().show()
            return

        path = os.path.dirname(ustr(self.filePath)) \
            if self.filePath else '.'
        if self.usingPascalVocFormat:
            filters = "Open Annotation XML file (%s)" % ' '.join(['*.xml'])
            filename = ustr(QFileDialog.getOpenFileName(self, '%s - Choose a xml file' % __appname__, path, filters))
            if filename:
                if isinstance(filename, (tuple, list)):
                    filename = filename[0]
            self.loadPascalXMLByFilename(filename)

    def openDirDialog(self, _value=False, dirpath=None):
        """Opens a dialog to select a directory of images to load."""
        if not self.mayContinue():
            return

        defaultOpenDirPath = dirpath if dirpath else '.'
        if self.lastOpenDir and os.path.exists(self.lastOpenDir):
            defaultOpenDirPath = self.lastOpenDir
        else:
            defaultOpenDirPath = os.path.dirname(self.filePath) if self.filePath else '.'

        self.targetDirPath = ustr(QFileDialog.getExistingDirectory(self,
                                                              '%s - Open Directory' % __appname__, defaultOpenDirPath,
                                                              QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks))
        self.defaultSaveDir = self.targetDirPath
        self.importDirImages(self.targetDirPath)

    def importDirImages(self, dirpath):
        """Imports and loads all images from a selected directory."""
        if not self.mayContinue() or not dirpath:
            return

        self.lastOpenDir = dirpath
        self.dirname = dirpath
        self.filePath = None
        self.fileListWidget.clear()
        self.mImgList = self.scanAllImages(dirpath)
        self.openNextImg()
        for imgPath in self.mImgList:
            item = QListWidgetItem(imgPath)
            self.fileListWidget.addItem(item)

    def verifyImg(self, _value=False):
        """Toggles the verification status of the currently loaded image."""
        # Proceding next image without dialog if having any label
        if self.filePath is not None:
            try:
                self.labelFile.toggleVerify()
            except AttributeError:
                # If the labelling file does not exist yet, create if and
                # re-save it with the verified attribute.
                self.saveFile()
                if self.labelFile != None:
                    self.labelFile.toggleVerify()
                else:
                    return

            self.canvas.verified = self.labelFile.verified
            self.paintCanvas()
            self.saveFile()

    def openPrevImg(self, _value=False):
        """Loads the previous image in the directory list."""
        # Proceding prev image without dialog if having any label
        if self.dirty is True:
            self.saveFile()

        if not self.mayContinue():
            return

        if len(self.mImgList) <= 0:
            return

        if self.filePath is None:
            return

        currIndex = self.mImgList.index(self.filePath)
        if currIndex - 1 >= 0:
            filename = self.mImgList[currIndex - 1]
            if filename:
                self.loadFile(filename)

    def openNextImg(self, _value=False):
        """Loads the next image in the directory list."""
        # Proceding prev image without dialog if having any label
        if self.dirty is True:
            self.saveFile()

        if not self.mayContinue():
            return

        if len(self.mImgList) <= 0:
            return

        filename = None
        if self.filePath is None:
            filename = self.mImgList[0]
        else:
            currIndex = self.mImgList.index(self.filePath)
            if currIndex + 1 < len(self.mImgList):
                filename = self.mImgList[currIndex + 1]

        if filename:
            self.loadFile(filename)

    def openFile(self, _value=False):
        """Opens a file dialog to select an image or label file to load."""
        if not self.mayContinue():
            return
        path = os.path.dirname(ustr(self.filePath)) if self.filePath else '.'
        formats = ['*.%s' % fmt.data().decode("ascii").lower() for fmt in QImageReader.supportedImageFormats()]
        filters = "Image & Label files (%s)" % ' '.join(formats + ['*%s' % LabelFile.suffix])
        filename = QFileDialog.getOpenFileName(self, '%s - Choose Image or Label file' % __appname__, path, filters)
        if filename:
            if isinstance(filename, (tuple, list)):
                filename = filename[0]
            self.loadFile(filename)

    def detectStoma(self, _value=False):
        """Triggers the stoma detection process for the currently loaded image or directory."""
        Dialog = QtWidgets.QDialog()
        ui = predict.selectPesos.Ui_Dialog()
        ui.setupUi(Dialog)
        x = Dialog.exec_()
        if ui.genera:
            if ui.default_1:#if it is by default
                # Detectamos estomas automáticamente, para ello vamos a usar las funciones del archivo detectStoma.py. Por eso
                # tenemos que diferenciar si hemos seleccionamos una imagen o un cjto.
                if len(self.mImgList) <= 1:
                    path = os.path.dirname(ustr(self.filePath)) if self.filePath else '.'
                    imgFileName = os.path.basename(self.filePath)
                    img = os.path.join(path, imgFileName)
                    detectStoma.mainImage(img)
                    if isinstance(img, (tuple, list)):
                        img = img[0]
                    self.loadFile(img)
                else:
                    path = os.path.dirname(ustr(self.filePath)) if self.filePath else '.'
                    box = QDialog()
                    box.setWindowFlags(box.windowFlags() | QtCore.Qt.CustomizeWindowHint)
                    box.setWindowFlags(box.windowFlags() & ~QtCore.Qt.WindowCloseButtonHint)
                    box.setWindowFlag(QtCore.Qt.WindowCloseButtonHint, False)
                    box.resize(179, 1)
                    box.setWindowTitle("Processing...")
                    box.show()
                    detectStoma.mainDataset(path)
                    box.close()
                    self.defaultSaveDir = self.targetDirPath
                    self.importDirImages(self.targetDirPath)

            else:#if it is not by default
                path = os.path.dirname(ustr(self.filePath)) if self.filePath else '.'
                model = notebooks.mainModel.selectModel(self, True)
                if model is not None:
                    box = QDialog()
                    box.setWindowFlags(box.windowFlags() | QtCore.Qt.CustomizeWindowHint)
                    box.setWindowFlags(box.windowFlags() & ~QtCore.Qt.WindowCloseButtonHint)
                    box.setWindowFlag(QtCore.Qt.WindowCloseButtonHint, False)
                    box.resize(179, 1)
                    box.setWindowTitle("Processing...")
                    box.show()
                    model.predict(path, path, float(ui.le_1))
                    box.close()
                self.defaultSaveDir = path
                self.importDirImages(path)

    def generarExcel(self):
        """Triggers the generation of an Excel report based on the current annotations."""
        self.saveFile()
        Dialog = QtWidgets.QDialog()
        ui = Ui_Dialog()
        ui.setupUi(Dialog)
        x = Dialog.exec_()

        # The main process waits until the dialog is closed.
        # Once the dialog has closed we can enter one of the parameters
        # of that dialog.
        if ui.genera:
            generaExcel(os.path.dirname(ustr(self.filePath)), ui.esca, self.shapeSize, ui.uni, ui.che2, ui.che3, ui.che4, ui.che5, ui.che6, ui.che7, ui.che8, ui.che9, ui.che10)
            self.setWindowIcon(QtGui.QIcon("resources/icons/excel.png"))
            QMessageBox.about(self, "Information", "Excel finished")
            self.setWindowIcon(newIcon("app"))

    def trainModel(self):
        """Initiates the process to generate training files or notebooks for model training."""
        self.saveFile()
        box = QDialog()
        box.setWindowFlags(box.windowFlags() | QtCore.Qt.CustomizeWindowHint)
        box.setWindowFlags(box.windowFlags() & ~QtCore.Qt.WindowCloseButtonHint)
        box.setWindowFlag(QtCore.Qt.WindowCloseButtonHint, False)
        box.resize(179, 1)
        box.setWindowTitle("Processing...")
        box.show()

        # The main process waits until the dialog is closed.
        # Once the dialog has closed we can enter one of the parameters
        # of that dialog.
        path = os.path.dirname(ustr(self.filePath)) if self.filePath else '.'
        notebooks.notebookYolo.notebookYOLO(path)
        box.close()
        path = os.path.dirname(ustr(self.filePath)) if self.filePath else '.'
        QMessageBox.about(self, "Information", "Notebook finished and save in " + path)

    def handleNewWindow(self):
        """Handles the creation of a new dialog window."""
        self.childWindow = Ui_Dialog(self)

    def saveFile(self, _value=False):
        """Saves the current annotations to the default or specified path."""
        if self.shapeSize is None:
            for shape in self.canvas.shapes:
                if shape.label=='scale':
                    self.shapeSize=shape.points[1].x() - shape.points[0].x()


        if self.defaultSaveDir is not None and len(ustr(self.defaultSaveDir)):
            if self.filePath:
                imgFileName = os.path.basename(self.filePath)
                savedFileName = os.path.splitext(imgFileName)[0]
                savedPath = os.path.join(ustr(self.defaultSaveDir), savedFileName)
                self._saveFile(savedPath)
        else:
            imgFileDir = os.path.dirname(self.filePath)
            imgFileName = os.path.basename(self.filePath)
            savedFileName = os.path.splitext(imgFileName)[0]
            savedPath = os.path.join(imgFileDir, savedFileName)
            self._saveFile(savedPath if self.labelFile
                           else self.saveFileDialog(removeExt=False))

    def saveFileAs(self, _value=False):
        """Saves the current annotations to a file specified by the user through a dialog."""
        assert not self.image.isNull(), "cannot save empty image"
        self._saveFile(self.saveFileDialog())

    def saveFileDialog(self, removeExt=True):
        """Opens a dialog for the user to specify the file path for saving annotations."""
        caption = '%s - Choose File' % __appname__
        filters = 'File (*%s)' % LabelFile.suffix
        openDialogPath = self.currentPath()
        dlg = QFileDialog(self, caption, openDialogPath, filters)
        dlg.setDefaultSuffix(LabelFile.suffix[1:])
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        filenameWithoutExtension = os.path.splitext(self.filePath)[0]
        dlg.selectFile(filenameWithoutExtension)
        dlg.setOption(QFileDialog.DontUseNativeDialog, False)
        if dlg.exec_():
            fullFilePath = ustr(dlg.selectedFiles()[0])
            if removeExt:
                return os.path.splitext(fullFilePath)[0]  # Return file path without the extension.
            else:
                return fullFilePath
        return ''

    def _saveFile(self, annotationFilePath):
        """Internal method to save annotations to a specified file."""
        if annotationFilePath and self.saveLabels(annotationFilePath):
            self.setClean()
            self.statusBar().showMessage('Saved to  %s' % annotationFilePath)
            self.statusBar().show()

    def closeFile(self, _value=False):
        """Closes the current file and prompts to save if there are unsaved changes."""
        self.saveFile()
        if not self.mayContinue():
            return

        self.resetState()
        self.setClean()
        self.toggleActions(False)
        self.canvas.setEnabled(False)
        self.actions.saveAs.setEnabled(False)

    def resetAll(self):
        """Resets all settings and restarts the application."""
        self.settings.reset()
        self.close()
        proc = QProcess()
        proc.startDetached(os.path.abspath(__file__))

    def mayContinue(self):
        """Checks if the user can proceed with an action, considering unsaved changes."""
        return True
        #not (self.dirty and not self.discardChangesDialog()

    def discardChangesDialog(self):
        """Opens a dialog asking the user if they want to discard unsaved changes."""
        yes, no = QMessageBox.Yes, QMessageBox.No
        msg = u'You have unsaved changes, proceed anyway?'
        return yes == QMessageBox.warning(self, u'Attention', msg, yes | no)

    def errorMessage(self, title, message):
        """Displays an error message dialog."""
        return QMessageBox.critical(self, title,
                                    '<p><b>%s</b></p>%s' % (title, message))

    def currentPath(self):
        """Returns the current working directory path."""
        return os.path.dirname(self.filePath) if self.filePath else '.'

    def chooseColor1(self):
        """Opens a color picker dialog for selecting the line color for shapes."""
        color = self.colorDialog.getColor(self.lineColor, u'Choose line color',
                                          default=DEFAULT_LINE_COLOR)
        if color:
            self.lineColor = color
            Shape.line_color = color
            self.canvas.setDrawingColor(color)
            self.canvas.update()
            self.setDirty()

    def deleteSelectedShape(self):
        """Deletes the currently selected shape from the canvas and label list."""
        if self.canvas.selectedShape.label == 'scale':
            self.shapeSize == None
            self.actions.excel.setEnabled(False)
        self.remLabel(self.canvas.deleteSelected())
        self.setDirty()
        if self.noShapes():
            for action in self.actions.onShapesPresent:
                action.setEnabled(False)
        self.saveFile()

    def chshapeLineColor(self):
        """Changes the line color of the selected shape through a color picker dialog."""
        color = self.colorDialog.getColor(self.lineColor, u'Choose line color',
                                          default=DEFAULT_LINE_COLOR)
        if color:
            self.canvas.selectedShape.line_color = color
            self.canvas.update()
            self.setDirty()

    def chshapeFillColor(self):
        """Changes the fill color of the selected shape through a color picker dialog."""
        color = self.colorDialog.getColor(self.fillColor, u'Choose fill color',
                                          default=DEFAULT_FILL_COLOR)
        if color:
            self.canvas.selectedShape.fill_color = color
            self.canvas.update()
            self.setDirty()

    def copyShape(self):
        """Copies the selected shape."""
        self.canvas.endMove(copy=True)
        self.addLabel(self.canvas.selectedShape)
        self.setDirty()

    def moveShape(self):
        """Moves the selected shape to a new position."""
        self.canvas.endMove(copy=False)
        self.setDirty()

    def loadPredefinedClasses(self, predefClassesFile):
        """Loads predefined class labels from a file."""
        if os.path.exists(predefClassesFile) is True:
            with codecs.open(predefClassesFile, 'r', 'utf8') as f:
                for line in f:
                    line = line.strip()
                    if self.labelHist is None:
                        self.labelHist = [line]
                    else:
                        self.labelHist.append(line)

    def loadPascalXMLByFilename(self, xmlPath):
        """Loads Pascal VOC XML annotations for the current image."""
        if self.filePath is None:
            return
        if os.path.isfile(xmlPath) is False:
            return

        self.set_format(FORMAT_PASCALVOC)

        tVocParseReader = PascalVocReader(xmlPath)
        shapes = tVocParseReader.getShapes()
        self.loadLabels(shapes)
        self.canvas.verified = tVocParseReader.verified

    def loadYOLOTXTByFilename(self, txtPath):
        """Loads YOLO format annotations for the current image."""
        if self.filePath is None:
            return
        if os.path.isfile(txtPath) is False:
            return

        self.set_format(FORMAT_YOLO)
        tYoloParseReader = YoloReader(txtPath, self.image)
        shapes = tYoloParseReader.getShapes()
        print(shapes)
        self.loadLabels(shapes)
        self.canvas.verified = tYoloParseReader.verified

    def togglePaintLabelsOption(self):
        """Toggles the option to display labels on the shapes in the canvas."""
        for shape in self.canvas.shapes:
            shape.paintLabel = self.displayLabelOption.isChecked()

    def toogleDrawSquare(self):
        """Toggles the option to draw shapes as squares or rectangles."""
        self.canvas.setDrawingShapeToSquare(self.drawSquaresOption.isChecked())


def inverted(color):
    """Generates a color that is the inverse of the input color (used for contrasting text or UI elements)."""
    return QColor(*[255 - v for v in color.getRgb()])


def read(filename, default=None):
    """Reads and returns the content of a file, or returns a default value if reading fails."""
    try:
        with open(filename, 'rb') as f:
            return f.read()
    except:
        return default


def get_main_app(argv=[]):
    """
    Standard boilerplate Qt application code.
    Do everything but app.exec_() -- so that we can test the application in one thread
    """
    app = QApplication(argv)
    app.setApplicationName(__appname__)
    app.setWindowIcon(newIcon("app"))
    # Tzutalin 201705+: Accept extra agruments to change predefined class file
    # Usage : labelImg.py image predefClassFile saveDir
    win = MainWindow(argv[1] if len(argv) >= 2 else None,
                     argv[2] if len(argv) >= 3 else os.path.join(
                         os.path.dirname(sys.argv[0]),
                         'data', 'predefined_classes.txt'),
                     argv[3] if len(argv) >= 4 else None)
    win.show()
    return app, win


def main():
    '''construct main app and run it'''
    app, _win = get_main_app(sys.argv)
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())
