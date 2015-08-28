from PySide import QtGui, QtCore
import maya.cmds as cmds
import maya.mel as mel
from pymel.all import mel as pa
import maya.OpenMayaUI as mui
import glob
import os
import json
import sys
import shiboken


MAYA_SCRIPT_DIR = cmds.internalVar(userScriptDir=True)
MIEXEC_HISTORY_FILE = os.path.join(MAYA_SCRIPT_DIR, "miExecutorHistory.txt")


# Define mel procedure to call the previous function
mel.eval("""
global proc callLastCommand(string $function)
{
    repeatLast -ac $function -acl "blah-blah....";
}
""")


# Get a list of full paths of each modules.
modules = glob.glob(
    os.path.normpath(os.path.dirname(__file__) + "/module/*.py"))

# Get a list of module names without extensions.
# Result: ['mayaNode', 'mentalray', etc....]
baseNames = [os.path.splitext(os.path.basename(i))[0]for
             i in modules]

# Get a list of module names without extensions but package names.
# Result: ['module.mayaNode', 'module.vray', etc....]
moduleNames = ['module.' + i for i in baseNames]

# Remove '__init__' from the lists
for i in moduleNames:
    if '__init__' in i:
        idx = moduleNames.index(i)
        del moduleNames[idx]
for i in baseNames:
    if '__init__' in i:
        idx = baseNames.index(i)
        del baseNames[idx]


def importer(*args):
    """ Funciton to load each module """
    return __import__(args[0], globals(), locals(), [])

# Import all modules in the module directory.
mods = map(importer, moduleNames)

# Create a list of module objects and reload them all
moduleObjects = []
for i in baseNames:
    exec("""moduleObjects.append(mods[0].%s)""" % i)
for module in moduleObjects:
    reload(module)


def getMayaWindow():
    ptr = mui.MQtUtil.mainWindow()
    return shiboken.wrapInstance(long(ptr), QtGui.QMainWindow)


class UI(QtGui.QWidget):
    """ main UI class """

    def closeExistingWindow(self):
        """ Close a window if exits """

        for qtapp in QtGui.QApplication.topLevelWidgets():
            try:
                if qtapp.__class__.__name__ == self.__class__.__name__:
                    qtapp.close()
            except:
                pass

    def __init__(self, parent=getMayaWindow()):
        super(UI, self).__init__(parent)
        self.closeExistingWindow()
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setFixedSize(200, 20)
        self.setWindowFlags(QtCore.Qt.Tool)
        self.setWindowFlags(QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint)
        self.setWindowTitle("miExecutor")

        # Use window transparent if the OS is OSX or Windows
        osType = sys.platform
        if osType == "darwin":
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        elif osType == "linux2":
            # Composite Window needs be enabled
            # in linux to enable window transparent
            pass
        elif osType == "win32":
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        else:
            pass

        # Dictionary that all commands and icon paths will be stored in.
        self.commandDict = {}

        # Attribute to check if item on the popup list is selected
        self._selected = None

        # 0: When return pressed without selecting any items
        #    on the completion list
        # 1: when any items on the completion list is selected by arrow keys
        # Default is 1
        self.executeType = 0

        # Create Data then UI
        self.createData()
        self.createUI()

    def createData(self):
        """ Create item models for completers """

        self.model = QtGui.QStandardItemModel()

        # Load json files as dicrectory.
        # key is command name, and its item is icon path.
        commandFile = os.path.normpath(
            os.path.join(MAYA_SCRIPT_DIR, "miExecutorCommands.json"))
        try:
            jsonDict = json.load(open(commandFile))
        except IOError:
            jsonDict = {}

        # Create a list of command names
        self.commands = [i for i in jsonDict]

        # Add all command names and icon paths to the the model(self.model)
        for num, command in enumerate(jsonDict):
            item = QtGui.QStandardItem(command)
            if os.path.isabs(jsonDict[command]) is True:
                iconPath = os.path.normpath(jsonDict[command])
                item.setIcon(QtGui.QIcon(iconPath))
            else:
                item.setIcon(QtGui.QIcon(":%s" % jsonDict[command]))
            self.model.setItem(num, 0, item)

        # Store the model(self.model) into the sortFilterProxy model
        self.filteredModel = QtGui.QSortFilterProxyModel(self)
        self.filteredModel.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.filteredModel.setSourceModel(self.model)

        # History model
        self.historyList = loadHistory()
        self.historyModel = QtGui.QStandardItemModel()
        for num, command in enumerate(self.historyList):
            item = QtGui.QStandardItem(command)
            if os.path.isabs(jsonDict[command]) is True:
                iconPath = os.path.normpath(jsonDict[command])
                item.setIcon(QtGui.QIcon(iconPath))
            else:
                item.setIcon(QtGui.QIcon(":%s" % jsonDict[command]))
            self.historyModel.setItem(num, 0, item)

    def createUI(self):
        """ Create UI """

        self.lineEdit = QtGui.QLineEdit(self)
        self.lineEdit.setFixedWidth(200)
        vbox = QtGui.QBoxLayout(QtGui.QBoxLayout.TopToBottom, self)
        vbox.setSpacing(0)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.addWidget(self.lineEdit)
        self.setLayout(vbox)

        # Set up QCompleter
        self.completer = QtGui.QCompleter()
        self.completer.setCompletionMode(
            QtGui.QCompleter.UnfilteredPopupCompletion)
        self.completer.highlighted.connect(self.selectionCallback)
        self.completer.setModel(self.filteredModel)
        self.completer.setObjectName("commandCompleter")

        # Setup QCompleter for history
        self.histCompleter = QtGui.QCompleter()
        self.histCompleter.setCompletionMode(
            QtGui.QCompleter.UnfilteredPopupCompletion)
        self.histCompleter.setModel(self.historyModel)
        self.histCompleter.setObjectName("historyCompleter")

        # Edit line Edit behavior
        self.lineEdit.setCompleter(self.completer)
        self.lineEdit.textEdited.connect(self.updateData)
        self.lineEdit.textChanged.connect(self.getCurrentCompletion)
        self.lineEdit.returnPressed.connect(self.initialExecution)
        self.lineEdit.setFocus()

    def keyPressEvent(self, event):
        """ Show history command list by down arrow key """

        key = event.key()
        if key == QtCore.Qt.Key_Down:
            self.lineEdit.setCompleter(self.histCompleter)
            self.histCompleter.complete()
        else:
            self.close()

    def updateData(self):
        """ Update current completion data """

        # If text is empty, change history completer back to
        # command completer
        currentText = self.lineEdit.text()
        if currentText == "":
            self.lineEdit.setCompleter(self.completer)

        # Set commands to case insensitive
        regExp = QtCore.QRegExp(self.lineEdit.text(),
                                QtCore.Qt.CaseInsensitive,
                                QtCore.QRegExp.RegExp)
        self.filteredModel.setFilterRegExp(regExp)

    def selectionCallback(self, selected):
        self._selected = selected
        self.executeType = 1
        return self._selected

    def getCurrentCompletion(self, *args):
        """ Get a command to be completed """

        compType = self.lineEdit.completer().objectName()
        if compType == "commandCompleter":
            self.curCompPrefix = self.completer.completionPrefix().lower()
            self.curCompList = [i for i
                                in self.commands
                                if self.curCompPrefix in i.lower()]
            try:
                self.currentCompletion = self.curCompList[0]
            except IndexError:
                self.currentCompletion = None

            currentCompletion = self.completer.currentCompletion()

            # If currentCompletion by QCompleter is empty, use the top item
            # in the self.curComList instead.
            if str(currentCompletion) == "":
                pass
            else:
                self.currentCompletion = currentCompletion

        elif compType == "historyCompleter":
            self.currentCompletion = self.lineEdit.text()

        else:
            pass

        return self.currentCompletion

    def initialExecution(self):
        """ Execute actuall command and register it to last command """

        try:
            # Run command
            self.secondaryExecution()
        except RuntimeError:
            cmds.warning("Command not found. No object created.")
            self.close()
            return

        # Send the last command to the mel procedure defined
        # at the begging of the script
        if self.lastCommand is not None:
            className = self.__class__.__name__
            pa.callLastCommand(
                """python(\"miExecutor_pyside.%s()._%s()\")""" % (
                    className, self.lastCommand))
        else:
            cmds.warning("Command not found. No object created.")

    def secondaryExecution(self):
        """ Execute command """

        # When return pressed without selecting any items
        # on the completion list
        if self.executeType == 0:
            if self.currentCompletion is None:
                self.close()
                self.lastCommand = None
            else:
                commandString = "self._%s()" % self.currentCompletion
                exec commandString
                self.close()
                self.lastCommand = self.currentCompletion
        # when any items on the completion list is selected by arrow keys
        elif self.executeType == 1:
            commandString = "self._%s()" % self._selected
            exec commandString
            self.close()
            self.lastCommand = self._selected
        else:
            pass

        updateHistory(self.lastCommand)
        return self.lastCommand


class MainClass():
    """ This is the main class which will interit all command classes
    from all command modules """

    pass

# Create a list of class objects.
CLASSLIST = [UI]
for i in baseNames:
    exec("""CLASSLIST.append(mods[0].%s.Commands)""" % i)

# Convert the list of classes to the tuple
# The second argument of 'type' only accept a tuple
CLASSES = tuple(CLASSLIST)


def inheritClasses():
    """ Re-difine MainClass to inherit all classes from other modules """

    global MainClass
    MainClass = type('MainClass', CLASSES, dict(MainClass.__dict__))


def mergeCommandDict():
    """ Combine all command dicrectories and create json files which includes
    all command names and their icons paths.  """

    miExec = MainClass()
    for item in baseNames:
        exec("miExec.commandDict.update(miExec.%sDict)" % item)
    outFilePath = os.path.normpath(
        os.path.join(MAYA_SCRIPT_DIR, "miExecutorCommands.json"))

    with open(outFilePath, 'w') as outFile:
        json.dump(miExec.commandDict,
                  outFile,
                  indent=4,
                  separators=(',', ':'),
                  sort_keys=True)


def loadHistory():
    """ Clear history list """

    if os.path.exists(MIEXEC_HISTORY_FILE):
        with open(MIEXEC_HISTORY_FILE, 'r') as histFile:
            histories = [i.rstrip() for i in histFile.readlines()]
            return histories
    else:
        # Create empty text file for history
        open(MIEXEC_HISTORY_FILE, 'a').close()


def updateHistory(command):
    """ Update and rewrite history list to file """

    historyList = loadHistory()
    if command in historyList:
        historyList.remove(command)
    historyList.insert(0, command)
    with open(MIEXEC_HISTORY_FILE, 'w') as histFile:
        for i in historyList:
            histFile.write(i + "\n")


# Show window.
def main():
    inheritClasses()
    mergeCommandDict()
    global miExec
    try:
        miExec.close()
    except:
        pass
    miExec = MainClass()
    miExec.show()

    # Move the window to the cursor position.
    pos = QtGui.QCursor.pos()
    miExec.move(
        pos.x() - (miExec.width() / 2), pos.y() - (miExec.height() / 2))
    miExec.activateWindow()
    miExec.raise_()


if __name__ == "__main__":
    pass
else:
    main()