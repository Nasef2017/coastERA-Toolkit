import os
from pathlib import Path
import traceback

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingException,
                       QgsProcessingParameterString,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterFolderDestination,
                       QgsProcessingParameterFileDestination,
                       QgsProject,
                       QgsRasterLayer)

AVAILABLE_VARS = [
    'significant_height_of_combined_wind_waves_and_swell',
    'peak_wave_period',
    'mean_wave_direction',
    'mean_wave_period',
    'significant_height_of_wind_waves',
    'mean_period_of_wind_waves',
    'mean_direction_of_wind_waves',
    'significant_height_of_total_swell',
    'mean_period_of_total_swell',
    'mean_direction_of_total_swell',
    'coefficient_of_drag_with_waves',
    '10m_u_component_of_wind',
    '10m_v_component_of_wind',
    'sea_surface_temperature',
    'mean_sea_level_pressure',
    '2m_temperature'
]

TIME_RESOLUTIONS = ["1h", "3h", "6h", "12h"]

class CoastERADownloadAlgorithm(QgsProcessingAlgorithm):
    
    API_URL = 'API_URL'
    API_KEY = 'API_KEY'
    LAT = 'LAT'
    LON = 'LON'
    PADDING = 'PADDING'
    START_DATE = 'START_DATE'
    END_DATE = 'END_DATE'
    TIME_RES = 'TIME_RES'
    VARIABLES = 'VARIABLES'
    OUTPUT_DIR = 'OUTPUT_DIR'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return CoastERADownloadAlgorithm()

    def name(self):
        return 'download_era5'

    def displayName(self):
        return self.tr('Download & Process ERA5 Data')

    def group(self):
        return self.tr('MetOcean Data')

    def groupId(self):
        return 'metocean'

    def shortHelpString(self):
        return self.tr("Downloads hourly ERA5 data from Copernicus CDS, extracts coastal engineering parameters, saves them to CSV and TPAR formats, and generates Wind/Wave roses.")

    def icon(self):
        return QIcon(os.path.join(os.path.dirname(__file__), 'icon.png'))

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterString(self.API_URL, self.tr('Copernicus API URL'), defaultValue='https://cds.climate.copernicus.eu/api'))
        self.addParameter(QgsProcessingParameterString(self.API_KEY, self.tr('Copernicus API Key'), defaultValue=' '))
        
        self.addParameter(QgsProcessingParameterNumber(self.LAT, self.tr('Target Latitude (Decimal Degrees)'), type=QgsProcessingParameterNumber.Double, defaultValue=34.5))
        self.addParameter(QgsProcessingParameterNumber(self.LON, self.tr('Target Longitude (Decimal Degrees)'), type=QgsProcessingParameterNumber.Double, defaultValue=-75.5))
        self.addParameter(QgsProcessingParameterNumber(self.PADDING, self.tr('Bounding Box Padding (Degrees)'), type=QgsProcessingParameterNumber.Double, defaultValue=0.5))
        
        self.addParameter(QgsProcessingParameterString(self.START_DATE, self.tr('Start Date (YYYY-MM-DD)'), defaultValue='2023-01-01'))
        self.addParameter(QgsProcessingParameterString(self.END_DATE, self.tr('End Date (YYYY-MM-DD)'), defaultValue='2023-01-31'))
        
        self.addParameter(QgsProcessingParameterEnum(self.TIME_RES, self.tr('Time Resolution'), options=TIME_RESOLUTIONS, defaultValue=1))
        
        self.addParameter(QgsProcessingParameterEnum(self.VARIABLES, self.tr('Product Variables'), options=AVAILABLE_VARS, allowMultiple=True, defaultValue=[0,1,2,3,4]))
        
        self.addParameter(QgsProcessingParameterFolderDestination(self.OUTPUT_DIR, self.tr('Output Directory')))

    def processAlgorithm(self, parameters, context, feedback):
        try:
            import cdsapi
            import xarray as xr
            import pandas as pd
            import numpy as np
        except ImportError as e:
            raise QgsProcessingException(f"Missing required library: {str(e)}\nPlease run: python -m pip install \"numpy<2.0.0\" cdsapi xarray pandas matplotlib windrose netCDF4 scipy")

        api_url = self.parameterAsString(parameters, self.API_URL, context).strip()
        api_key = self.parameterAsString(parameters, self.API_KEY, context).strip()
        target_lat = self.parameterAsDouble(parameters, self.LAT, context)
        target_lon = self.parameterAsDouble(parameters, self.LON, context)
        pad = self.parameterAsDouble(parameters, self.PADDING, context)
        start_date_str = self.parameterAsString(parameters, self.START_DATE, context).strip()
        end_date_str = self.parameterAsString(parameters, self.END_DATE, context).strip()
        time_res_idx = self.parameterAsEnum(parameters, self.TIME_RES, context)
        var_indices = self.parameterAsEnums(parameters, self.VARIABLES, context)
        save_dir = self.parameterAsString(parameters, self.OUTPUT_DIR, context)
        
        if not save_dir:
            raise QgsProcessingException("Output directory is required.")
        if not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)

        variables = [AVAILABLE_VARS[i] for i in var_indices]
        
        # Date & Time parsing
        try:
            dates = pd.date_range(start=start_date_str, end=end_date_str)
        except Exception:
            raise QgsProcessingException(f"Invalid date format. Please use YYYY-MM-DD. Got: {start_date_str} to {end_date_str}")
            
        res_str = TIME_RESOLUTIONS[time_res_idx]
        if res_str == "1h": times = [f"{str(i).zfill(2)}:00" for i in range(24)]
        elif res_str == "3h": times = [f"{str(i).zfill(2)}:00" for i in range(0, 24, 3)]
        elif res_str == "6h": times = [f"{str(i).zfill(2)}:00" for i in range(0, 24, 6)]
        elif res_str == "12h": times = ["00:00", "12:00"]
        else: times = [f"{str(i).zfill(2)}:00" for i in range(24)]

        # Setup Credentials
        feedback.pushInfo("Configuring Copernicus CDS API credentials...")
        cdsapirc_path = Path.home() / '.cdsapirc'
        with open(cdsapirc_path, 'w') as f:
            f.write(f"url: {api_url}\nkey: {api_key}\n")

        # Request Download
        feedback.pushInfo(f"Downloading data for Lat: {target_lat}, Lon: {target_lon}...")
        file_name = os.path.join(save_dir, 'offshore_waves.zip')
        req_params = {
            "location": {"longitude": target_lon, "latitude": target_lat},
            "date": [f"{start_date_str}/{end_date_str}"],
            "variable": variables
        }
        if len(times) < 24:
            req_params["time"] = times

        c = cdsapi.Client()
        
        # Override the print function globally or capture stdout? 
        # cdsapi prints to stdout, we can't easily capture it without redirecting sys.stdout.
        import sys
        import io
        class FeedbackWriter(io.StringIO):
            def __init__(self, feedback):
                super().__init__()
                self.feedback = feedback
            def write(self, s):
                try:
                    if s and s.strip() and not s.strip().startswith('%'): 
                        # Optionally filter out some tqdm raw bars if they look too messy in QGIS log
                        self.feedback.pushInfo(s.strip())
                except Exception:
                    pass
                return len(s) if s else 0
            def flush(self): pass
            def isatty(self): return False
        
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        
        fw = FeedbackWriter(feedback)
        sys.stdout = fw
        # QGIS sets sys.stderr to None or read-only logger sometimes. cdsapi uses tqdm which writes to sys.stderr
        sys.stderr = fw
        
        try:
            c.retrieve('reanalysis-era5-single-levels-timeseries', req_params, file_name)
        except Exception as e:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            raise QgsProcessingException(f"CDS API Download Failed: {str(e)}")
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        if feedback.isCanceled():
            return {}

        feedback.pushInfo("Download complete. Extracting and Processing Data...")
        
        import zipfile
        import glob

        def get_point_df(nc_path):
            try:
                ds = xr.open_dataset(nc_path, engine='netcdf4')
                if 'latitude' in ds.dims and ds.dims['latitude'] > 1:
                    ds_point = ds.sel(latitude=target_lat, longitude=target_lon, method='nearest')
                else:
                    ds_point = ds.squeeze()
                df_part = ds_point.to_dataframe().reset_index()
            except Exception:
                df_part = pd.read_csv(nc_path, comment='#')
            
            if 'valid_time' in df_part.columns and 'time' not in df_part.columns:
                df_part.rename(columns={'valid_time': 'time'}, inplace=True)
            if 'time' in df_part.columns and str(df_part['time'].dtype) == 'object':
                df_part['time'] = pd.to_datetime(df_part['time'])
            
            cols_to_drop = ['latitude', 'longitude', 'number', 'step', 'surface', 'expver']
            cols_to_keep = [c for c in df_part.columns if c not in cols_to_drop]
            return df_part[cols_to_keep]

        df = None
        extracted_ncs = []
        
        if zipfile.is_zipfile(file_name):
            extract_dir = os.path.join(save_dir, 'era5_extracted')
            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(file_name, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            nc_files = glob.glob(os.path.join(extract_dir, '*.nc'))
            csv_files = glob.glob(os.path.join(extract_dir, '*.csv'))
            all_files = nc_files + csv_files
            extracted_ncs.extend(nc_files)
            
            for nc_path in all_files:
                if feedback.isCanceled(): return {}
                df_part = get_point_df(nc_path)
                if df is None:
                    df = df_part
                else:
                    df_part = df_part.drop_duplicates(subset=['time'])
                    df = pd.merge(df, df_part, on='time', how='outer')
        else:
            df = get_point_df(file_name)
            df = df.drop_duplicates(subset=['time'])
            if file_name.endswith('.nc'):
                extracted_ncs.append(file_name)

        if df is None or df.empty:
            raise QgsProcessingException("No data could be extracted.")

        df.sort_values(by='time', inplace=True)
        
        rename_map = {
            'swh': 'Hs (m)', 'pp1d': 'Tp (s)', 'mwd': 'Dir (° Met, True North)', 'mwp': 'Tm (s)',
            'shww': 'Hs_wind (m)', 'mpww': 'Tm_wind (s)', 'mdww': 'Dir_wind (° Met, True North)',
            'shts': 'Hs_swell (m)', 'mpts': 'Tm_swell (s)', 'mdts': 'Dir_swell (° Met, True North)',
            'cdww': 'Cd', 'u10': 'U10 (m/s)', 'v10': 'V10 (m/s)', 'si10': 'WindSpd (m/s)',
            'dwi': 'WindDir (° Met, True North)', 'sst': 'SST (K)', 'msl': 'MSLP (Pa)', 't2m': 'T2m (K)'
        }
        
        current_rename = {k: v for k, v in rename_map.items() if k in df.columns}
        df.rename(columns=current_rename, inplace=True)
        
        cols_to_keep = ['time'] + list(current_rename.values())
        for col in df.columns:
            if col not in cols_to_keep and col not in ['latitude', 'longitude', 'number', 'step', 'surface', 'valid_time']:
                cols_to_keep.append(col)
                
        df = df[[c for c in cols_to_keep if c in df.columns]]
        df.set_index('time', inplace=True)
        df.dropna(inplace=True)
        
        req_start = pd.to_datetime(start_date_str)
        req_end = pd.to_datetime(end_date_str) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        df = df[(df.index >= req_start) & (df.index <= req_end)]
        
        if 'U10 (m/s)' in df.columns and 'V10 (m/s)' in df.columns:
            df['WindSpd (m/s)'] = np.sqrt(df['U10 (m/s)']**2 + df['V10 (m/s)']**2)
            df['WindDir (° Met, True North)'] = (270 - np.degrees(np.arctan2(df['V10 (m/s)'], df['U10 (m/s)']))) % 360
            current_rename['si10'] = 'WindSpd (m/s)'
            current_rename['dwi'] = 'WindDir (° Met, True North)'
        
        csv_path = os.path.join(save_dir, 'wave_data.csv')
        with open(csv_path, 'w', encoding='utf-8') as f:
            f.write("# ERA5 Timeseries Data Extract\n")
            f.write(f"# Extracted for Lat: {target_lat}, Lon: {target_lon}\n")
            for k, v in current_rename.items():
                f.write(f"#   {v} = {k}\n")
            f.write("#\n")
        df.to_csv(csv_path, mode='a')
        feedback.pushInfo(f"Saved CSV data to '{csv_path}'")

        if 'Hs (m)' in df.columns and ('Tp (s)' in df.columns or 'Tm (s)' in df.columns) and 'Dir (° Met, True North)' in df.columns:
            tpar_path = os.path.join(save_dir, 'boundary_conditions.tpar')
            period_col = 'Tp (s)' if 'Tp (s)' in df.columns else 'Tm (s)'
            with open(tpar_path, 'w') as f:
                f.write('TPAR\n')
                for index, row in df.iterrows():
                    t_str = index.strftime('%Y%m%d.%H%M')
                    f.write(f"{t_str} {row['Hs (m)']:.2f} {row[period_col]:.2f} {row['Dir (° Met, True North)']:.2f} 20.0\n")
            feedback.pushInfo(f"Saved boundary conditions as '{tpar_path}'")

        # Plotting (Using matplotlib inside QGIS can be tricky without Agg backend if showing GUI, but saving to file is fine)
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            
            if 'Hs (m)' in df.columns and 'Dir (° Met, True North)' in df.columns:
                try:
                    from windrose import WindroseAxes
                    import matplotlib.cm as cm
                    fig = plt.figure(figsize=(10, 8))
                    ax = WindroseAxes(fig, [0.1, 0.1, 0.6, 0.8])
                    fig.add_axes(ax)
                    ax.bar(df['Dir (° Met, True North)'], df['Hs (m)'], normed=True, opening=0.8, edgecolor='white', cmap=cm.viridis)
                    ax.set_title('Wave Rose')
                    ax.set_legend(title="Hs (m)", bbox_to_anchor=(1.1, 0.5), loc="center left")
                    rose_path = os.path.join(save_dir, 'wave_rose.png')
                    plt.savefig(rose_path, dpi=300, bbox_inches='tight')
                    plt.close(fig)
                    feedback.pushInfo("Saved Wave Rose.")
                except ImportError:
                    feedback.pushWarning("windrose library not found. Skipping Wave Rose.")

            if all(v in df.columns for v in ['WindSpd (m/s)', 'WindDir (° Met, True North)']):
                try:
                    from windrose import WindroseAxes
                    import matplotlib.cm as cm
                    fig = plt.figure(figsize=(10, 8))
                    ax = WindroseAxes(fig, [0.1, 0.1, 0.6, 0.8])
                    fig.add_axes(ax)
                    ax.bar(df['WindDir (° Met, True North)'], df['WindSpd (m/s)'], normed=True, opening=0.8, edgecolor='white', cmap=cm.viridis)
                    ax.set_title('Wind Rose')
                    ax.set_legend(title="WindSpd (m/s)", bbox_to_anchor=(1.1, 0.5), loc="center left")
                    wind_rose_path = os.path.join(save_dir, 'wind_rose.png')
                    plt.savefig(wind_rose_path, dpi=300, bbox_inches='tight')
                    plt.close(fig)
                    feedback.pushInfo("Saved Wind Rose.")
                except ImportError:
                    pass
                    
            vars_to_plot = [c for c in ['Hs (m)', 'Tp (s)', 'Dir (° Met, True North)', 'WindSpd (m/s)', 'WindDir (° Met, True North)'] if c in df.columns]
            if vars_to_plot:
                fig, axes = plt.subplots(len(vars_to_plot), 1, figsize=(10, 3*len(vars_to_plot)), sharex=True)
                if len(vars_to_plot) == 1: axes = [axes]
                colors = ['blue', 'orange', 'green', 'purple', 'red']
                for idx, (var, ax) in enumerate(zip(vars_to_plot, axes)):
                    if 'Dir' in var:
                        ax.scatter(df.index, df[var], color=colors[idx % len(colors)], s=5, label=var)
                        ax.set_ylim(0, 360)
                    else:
                        ax.plot(df.index, df[var], color=colors[idx % len(colors)], label=var)
                    ax.set_ylabel(var)
                    ax.grid(True)
                    ax.legend()
                plt.tight_layout()
                plt.savefig(os.path.join(save_dir, 'timeseries.png'), dpi=300)
                plt.close(fig)
                
        except Exception as e:
            feedback.pushWarning(f"Plotting failed: {str(e)}")

        # Load into QGIS Map Canvas
        for nc_path in extracted_ncs:
            if os.path.exists(nc_path):
                layer_name = os.path.basename(nc_path)
                layer = QgsRasterLayer(nc_path, layer_name)
                if layer.isValid():
                    QgsProject.instance().addMapLayer(layer)
                    feedback.pushInfo(f"Loaded layer: {layer_name}")
                else:
                    layer = QgsRasterLayer(f"NETCDF:\"{nc_path}\"", layer_name)
                    if layer.isValid():
                        QgsProject.instance().addMapLayer(layer)

        return {self.OUTPUT_DIR: save_dir}
