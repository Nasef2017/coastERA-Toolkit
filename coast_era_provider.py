import os
from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon
from .coast_era_algorithm import CoastERADownloadAlgorithm

class CoastERAProvider(QgsProcessingProvider):
    def __init__(self):
        super().__init__()
        self.plugin_dir = os.path.dirname(__file__)

    def loadAlgorithms(self):
        self.addAlgorithm(CoastERADownloadAlgorithm())

    def id(self):
        return 'coastera'

    def name(self):
        return 'CoastERA Toolkit'

    def icon(self):
        return QIcon(os.path.join(self.plugin_dir, 'icon.png'))

    def longName(self):
        return 'CoastERA Toolkit'
