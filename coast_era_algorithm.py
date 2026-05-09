
import os
import sys
import io
from pathlib import Path
import traceback

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtGui import QIcon, QColor, QFont
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterString,
    QgsProcessingParameterNumber,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterPoint,
    QgsProject,
    QgsVectorLayer,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling,
    QgsTextFormat,
    QgsTextBufferSettings,
    QgsWkbTypes,
    QgsProcessingParameterBoolean,
    QgsMarkerSymbol,
    QgsSingleSymbolRenderer,
    QgsSymbolLayer,
    QgsProperty,
    QgsSymbol,
    Qgis,
    QgsSvgMarkerSymbolLayer,
    QgsRuleBasedRenderer
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
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
    '2m_temperature',
]

TIME_RESOLUTIONS = ["1h", "3h", "6h", "12h"]

# Short ERA5 variable names AND Full names -> human-readable column names (meteorological convention)
RENAME_MAP = {
    # Short names (NetCDF default)
    'swh':  'significant_height_of_combined_wind_waves_and_swell [m] (swh)',
    'pp1d': 'peak_wave_period [s] (pp1d)',
    'mwd':  'mean_wave_direction [deg] (mwd)',
    'mwp':  'mean_wave_period [s] (mwp)',
    'shww': 'significant_height_of_wind_waves [m] (shww)',
    'mpww': 'mean_period_of_wind_waves [s] (mpww)',
    'mdww': 'mean_direction_of_wind_waves [deg] (mdww)',
    'shts': 'significant_height_of_total_swell [m] (shts)',
    'mpts': 'mean_period_of_total_swell [s] (mpts)',
    'mdts': 'mean_direction_of_total_swell [deg] (mdts)',
    'cdww': 'coefficient_of_drag_with_waves (cdww)',
    'u10':  '10m_u_component_of_wind [m/s] (u10)',
    'v10':  '10m_v_component_of_wind [m/s] (v10)',
    'sst':  'sea_surface_temperature [K] (sst)',
    'msl':  'mean_sea_level_pressure [Pa] (msl)',
    't2m':  '2m_temperature [K] (t2m)',
    
    # Full names (Timeseries CSV default)
    'significant_height_of_combined_wind_waves_and_swell': 'significant_height_of_combined_wind_waves_and_swell [m] (swh)',
    'peak_wave_period': 'peak_wave_period [s] (pp1d)',
    'mean_wave_direction': 'mean_wave_direction [deg] (mwd)',
    'mean_wave_period': 'mean_wave_period [s] (mwp)',
    'significant_height_of_wind_waves': 'significant_height_of_wind_waves [m] (shww)',
    'mean_period_of_wind_waves': 'mean_period_of_wind_waves [s] (mpww)',
    'mean_direction_of_wind_waves': 'mean_direction_of_wind_waves [deg] (mdww)',
    'significant_height_of_total_swell': 'significant_height_of_total_swell [m] (shts)',
    'mean_period_of_total_swell': 'mean_period_of_total_swell [s] (mpts)',
    'mean_direction_of_total_swell': 'mean_direction_of_total_swell [deg] (mdts)',
    'coefficient_of_drag_with_waves': 'coefficient_of_drag_with_waves (cdww)',
    '10m_u_component_of_wind': '10m_u_component_of_wind [m/s] (u10)',
    '10m_v_component_of_wind': '10m_v_component_of_wind [m/s] (v10)',
    'sea_surface_temperature': 'sea_surface_temperature [K] (sst)',
    'mean_sea_level_pressure': 'mean_sea_level_pressure [Pa] (msl)',
    '2m_temperature': '2m_temperature [K] (t2m)',
}


# ---------------------------------------------------------------------------
# Algorithm
# ---------------------------------------------------------------------------
class CoastERADownloadAlgorithm(QgsProcessingAlgorithm):

    # Parameter keys
    CDS_URL = 'CDS_URL'
    CDS_KEY = 'CDS_KEY'
    POINT_LAYER = 'POINT_LAYER'
    CANVAS_POINT = 'CANVAS_POINT'
    PADDING = 'PADDING'
    START_DATE = 'START_DATE'
    END_DATE = 'END_DATE'
    TIME_RES = 'TIME_RES'
    VARIABLES = 'VARIABLES'
    OUTPUT_DIR = 'OUTPUT_DIR'
    GENERATE_WAVEROSE = 'GENERATE_WAVEROSE'
    GENERATE_WINDROSE = 'GENERATE_WINDROSE'
    GENERATE_TIMESERIES = 'GENERATE_TIMESERIES'

    # ------------------------------------------------------------------ meta
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
        return """
        <div style="font-family: Arial, sans-serif; line-height: 1.4;">
            <h2 style="margin-bottom: 5px; color: #2E86C1;">🌊 MetOcean Data v1.2</h2>
            <p style="margin-top: 0; margin-bottom: 10px;">
                Automated downloading, processing, and visualization of <b>Copernicus ERA5</b> metocean data.
            </p>

            
            <ul style="margin-top: 0; margin-bottom: 10px; padding-left: 20px;">
                <li><b>Interactive Selection:</b> Pick points directly from the map canvas.</li>
                <li><b>Drag-and-Drop:</b> Support for point layers via drag-and-drop.</li>
                <li><b>Quick Viz:</b> Immediate Wave Rose pop-ups within the layout.</li>
                <li><b>Data Export:</b> Direct download for selected point datasets.</li>
            </ul>

            <b style="display: block; margin-bottom: 2px;">⚙️ Core Features:</b>
            <ul style="margin-top: 0; margin-bottom: 10px; padding-left: 20px;">
                <li>Exports to <b>CSV</b> and <b>TPAR</b> formats.</li>
                <li>Generates <b>Interactive HTML Time-series</b> plots.</li>
            </ul>

            <p style="margin-top: 10px; border-top: 1px solid #ccc; padding-top: 5px; font-size: 0.9em;">
                <b>Developer:</b> Mohamed Aly Nasef
            </p>
        </div>
        """

    def helpString(self):
        return self.shortHelpString()

    def icon(self):
        icon_path = os.path.join(os.path.dirname(__file__), 'icon.png')
        return QIcon(icon_path)

    # --------------------------------------------------------- initAlgorithm
    def initAlgorithm(self, config=None):
        # --- API Credentials ---
        self.addParameter(
            QgsProcessingParameterString(
                self.CDS_URL,
                self.tr('CDS API URL'),
                defaultValue='https://cds.climate.copernicus.eu/api',
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.CDS_KEY,
                self.tr('CDS API Key (UID:API-KEY)'),
                optional=True,
            )
        )

        # --- Coordinate inputs (dual-option) ---
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.POINT_LAYER,
                self.tr('Point Layer (optional – overrides canvas point)'),
                [QgsProcessing.TypeVectorPoint],
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterPoint(
                self.CANVAS_POINT,
                self.tr('Or click a point on the map canvas'),
                optional=True,
            )
        )

        # --- Bounding box padding ---
        self.addParameter(
            QgsProcessingParameterNumber(
                self.PADDING,
                self.tr('Bounding Box Padding (Degrees)'),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.5,
            )
        )

        # --- Date range ---
        self.addParameter(
            QgsProcessingParameterString(
                self.START_DATE,
                self.tr('Start Date (YYYY-MM-DD)'),
                defaultValue='2023-01-01',
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.END_DATE,
                self.tr('End Date (YYYY-MM-DD)'),
                defaultValue='2023-01-31',
            )
        )

        # --- Time resolution ---
        self.addParameter(
            QgsProcessingParameterEnum(
                self.TIME_RES,
                self.tr('Time Resolution'),
                options=TIME_RESOLUTIONS,
                defaultValue=0,
            )
        )

        # --- Variables ---
        self.addParameter(
            QgsProcessingParameterEnum(
                self.VARIABLES,
                self.tr('Product Variables'),
                options=AVAILABLE_VARS,
                allowMultiple=True,
                defaultValue=[0, 1, 2, 3],
            )
        )

        # --- Wave Rose ---
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.GENERATE_WAVEROSE,
                self.tr('Generate Wave Rose (SVG)'),
                defaultValue=True,
            )
        )

        # --- Wind Rose ---
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.GENERATE_WINDROSE,
                self.tr('Generate Wind Rose (SVG)'),
                defaultValue=True,
            )
        )

        # --- Timeseries Plot ---
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.GENERATE_TIMESERIES,
                self.tr('Generate Interactive Timeseries (HTML)'),
                defaultValue=True,
            )
        )

        # --- Output folder ---
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_DIR,
                self.tr('Output Directory'),
            )
        )

    # ------------------------------------------------------ processAlgorithm
    def processAlgorithm(self, parameters, context, feedback):
        # ---- Import heavy deps -------------------------------------------
        try:
            import cdsapi
            import xarray as xr
            import pandas as pd
            import numpy as np
        except ImportError as e:
            raise QgsProcessingException(
                f"Missing required library: {e}\n"
                "Run: python -m pip install \"numpy<2.0.0\" cdsapi xarray pandas netCDF4 scipy plotly"
            )

        # ---- Common parameters -------------------------------------------
        cds_url        = self.parameterAsString(parameters, self.CDS_URL, context).strip()
        cds_key        = self.parameterAsString(parameters, self.CDS_KEY, context).strip()
        pad            = self.parameterAsDouble(parameters, self.PADDING, context)
        start_date_str = self.parameterAsString(parameters, self.START_DATE, context).strip()
        end_date_str   = self.parameterAsString(parameters, self.END_DATE,   context).strip()
        time_res_idx   = self.parameterAsEnum(parameters, self.TIME_RES, context)
        var_indices    = self.parameterAsEnums(parameters, self.VARIABLES, context)
        gen_waverose   = self.parameterAsBoolean(parameters, self.GENERATE_WAVEROSE, context)
        gen_windrose   = self.parameterAsBoolean(parameters, self.GENERATE_WINDROSE, context)
        gen_timeseries = self.parameterAsBoolean(parameters, self.GENERATE_TIMESERIES, context)
        save_dir       = self.parameterAsString(parameters, self.OUTPUT_DIR, context)

        if not save_dir:
            raise QgsProcessingException("Output directory is required.")
        os.makedirs(save_dir, exist_ok=True)

        variables = [AVAILABLE_VARS[i] for i in var_indices]

        # ---- Dates -----------------------------------------------------------
        try:
            dates = pd.date_range(start=start_date_str, end=end_date_str)
            num_days = (pd.to_datetime(end_date_str) - pd.to_datetime(start_date_str)).days + 1
        except Exception:
            raise QgsProcessingException(
                f"Invalid date format. Use YYYY-MM-DD. Got: {start_date_str} to {end_date_str}"
            )

        res_str = TIME_RESOLUTIONS[time_res_idx]
        if   res_str == "1h":  times = [f"{h:02d}:00" for h in range(24)]
        elif res_str == "3h":  times = [f"{h:02d}:00" for h in range(0, 24, 3)]
        elif res_str == "6h":  times = [f"{h:02d}:00" for h in range(0, 24, 6)]
        elif res_str == "12h": times = ["00:00", "12:00"]
        else:                  times = [f"{h:02d}:00" for h in range(24)]

        # Determine total requested items for limits check
        num_items = num_days * len(times) * len(variables)

        # ---- Collect points in EPSG:4326 ------------------------------------
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        points_wgs84 = []   # list of (lon, lat, label)

        # Priority 1: Vector Layer
        source = self.parameterAsSource(parameters, self.POINT_LAYER, context)
        if source is not None:
            src_crs = source.sourceCrs()
            xform   = QgsCoordinateTransform(src_crs, wgs84, context.transformContext())
            
            for feat in source.getFeatures():
                geom = feat.geometry()
                if geom.isNull():
                    continue
                
                # Handle standard Point or MultiPoint extraction properly
                if geom.isMultipart():
                    pt = geom.asMultiPoint()[0]
                else:
                    pt = geom.asPoint()
                
                pt_wgs84 = xform.transform(pt)
                label = feat.attribute(0) if feat.fields().count() > 0 else f"Pt_{len(points_wgs84)+1}"
                points_wgs84.append((pt_wgs84.x(), pt_wgs84.y(), str(label)))
            feedback.pushInfo(f"Loaded {len(points_wgs84)} point(s) from vector layer.")

        # Priority 2: Canvas Pick Point
        # Safely verify it actually exists before evaluating
        if not points_wgs84:
            canvas_pt_raw = parameters.get(self.CANVAS_POINT)
            if canvas_pt_raw not in (None, '', QVariant()):
                try:
                    canvas_pt  = self.parameterAsPoint(parameters, self.CANVAS_POINT, context)
                    canvas_crs = self.parameterAsPointCrs(parameters, self.CANVAS_POINT, context)
                    
                    if canvas_crs.isValid() and canvas_crs != wgs84:
                        xform = QgsCoordinateTransform(canvas_crs, wgs84, context.transformContext())
                        pt_wgs84 = xform.transform(canvas_pt)
                    else:
                        pt_wgs84 = canvas_pt
                        
                    points_wgs84.append((pt_wgs84.x(), pt_wgs84.y(), "CanvasPoint"))
                    feedback.pushInfo(f"Using canvas point: Lon={pt_wgs84.x():.4f}, Lat={pt_wgs84.y():.4f}")
                except Exception as e:
                    feedback.pushWarning(f"Failed to extract canvas point: {str(e)}")

        if not points_wgs84:
            raise QgsProcessingException(
                "No location provided! Please either provide a Point Layer OR click a point on the map canvas."
            )

        # ---- CDS credentials check ------------------------------------------
        has_gui_creds = bool(cds_url and cds_key)
        has_file_creds = (Path.home() / '.cdsapirc').exists()
        has_env_creds = ('CDSAPI_URL' in os.environ and 'CDSAPI_KEY' in os.environ)

        if not (has_gui_creds or has_file_creds or has_env_creds):
            raise QgsProcessingException(
                "Copernicus CDS API credentials not found.\n"
                "Please enter your URL and Key in the GUI, OR configure ~/.cdsapirc, "
                "OR set CDSAPI_URL and CDSAPI_KEY env variables."
            )

        # ---- Redirect stdout/stderr so cdsapi logs appear in QGIS -----------
        class _FeedbackWriter(io.StringIO):
            def __init__(self, fb):
                super().__init__()
                self._fb = fb
            def write(self, s):
                try:
                    if s and s.strip() and not s.strip().startswith('%'):
                        self._fb.pushInfo(s.strip())
                except Exception:
                    pass
                return len(s) if s else 0
            def flush(self): pass
            def isatty(self): return False

        # ================================================================
        # Main loop – one API call per point
        # ================================================================
        n_points = len(points_wgs84)
        created_layers = []

        for pt_idx, (lon, lat, pt_label) in enumerate(points_wgs84):
            if feedback.isCanceled():
                return {}

            feedback.setProgress(int(pt_idx / n_points * 80))
            feedback.pushInfo(
                f"\n[{pt_idx+1}/{n_points}] Processing: '{pt_label}'  "
                f"Lat={lat:.4f}, Lon={lon:.4f}"
            )

            # ---- Download ------------------------------------------------
            safe_name  = "".join(c if c.isalnum() or c in "-_." else "_" for c in pt_label)
            # Append coordinates to the base name for outputs
            coord_suffix = f"_{abs(lat):.4f}{'N' if lat>=0 else 'S'}_{abs(lon):.4f}{'E' if lon>=0 else 'W'}"
            safe_name += coord_suffix

            nc_file = os.path.join(save_dir, f"era5_{safe_name}.nc")

            # Standard Area Parameters
            req_params = {
                "product_type": "reanalysis",
                "format": "netcdf",
                "variable": variables,
                "date": f"{start_date_str}/{end_date_str}",
                "area": [lat + pad, lon - pad, lat - pad, lon + pad],
            }
            if len(times) < 24:
                req_params["time"] = times

            old_out, old_err = sys.stdout, sys.stderr
            fw = _FeedbackWriter(feedback)
            sys.stdout = fw
            sys.stderr = fw
            
            try:
                # Pass credentials if entered in the GUI; otherwise let cdsapi auto-detect
                if has_gui_creds:
                    c = cdsapi.Client(url=cds_url, key=cds_key)
                else:
                    c = cdsapi.Client()
                    
                best_lat, best_lon = lat, lon
                pf_checked = False

                def ensure_preflight():
                    nonlocal best_lat, best_lon, pf_checked
                    if pf_checked: return
                    pf_checked = True
                    wave_vars = [v for v in variables if 'wave' in v.lower() or 'swh' in v.lower() or 'mwd' in v.lower() or 'mwp' in v.lower() or 'significant' in v.lower()]
                    if not wave_vars: return
                    feedback.pushInfo("  Performing pre-flight check to ensure timeseries point is not on ERA5 land mask...")
                    pf_nc = os.path.join(save_dir, f"preflight_{safe_name}.nc")
                    pf_req = {
                        "product_type": "reanalysis",
                        "format": "netcdf",
                        "variable": [wave_vars[0]],
                        "date": f"{start_date_str}/{start_date_str}",
                        "time": "12:00",
                        "area": [lat + pad, lon - pad, lat - pad, lon + pad],
                    }
                    try:
                        c.retrieve('reanalysis-era5-single-levels', pf_req, pf_nc)
                        import xarray as xr
                        ds_pf = xr.open_dataset(pf_nc)
                        w_var = next((v for v in ds_pf.data_vars if v != 'crs'), None)
                        if w_var:
                            ds_pt = ds_pf.sel(latitude=lat, longitude=lon, method='nearest')
                            if ds_pt[w_var].isnull().all().item():
                                mean_wave = ds_pf[w_var].mean(dim=[d for d in ds_pf[w_var].dims if d not in ['latitude', 'longitude']], skipna=False)
                                df_grid = mean_wave.to_dataframe().reset_index()
                                df_valid = df_grid.dropna(subset=[w_var])
                                if not df_valid.empty:
                                    df_valid['dist_sq'] = (df_valid['latitude'] - lat)**2 + (df_valid['longitude'] - lon)**2
                                    best_row = df_valid.loc[df_valid['dist_sq'].idxmin()]
                                    best_lat, best_lon = float(best_row['latitude']), float(best_row['longitude'])
                                    feedback.pushInfo(f"  Point mapped to land. Snapped timeseries request to nearest offshore: Lat={best_lat:.4f}, Lon={best_lon:.4f}")
                                else:
                                    feedback.pushWarning("  Warning: No valid offshore points found in the padding area. Consider increasing padding.")
                        ds_pf.close()
                        if os.path.exists(pf_nc):
                            try:
                                os.remove(pf_nc)
                            except:
                                pass
                    except Exception as pf_e:
                        feedback.pushWarning(f"  Pre-flight check failed: {pf_e}. Proceeding with original coordinates.")

                # CONDITION: If request is too large (> 100,000 items), use timeseries endpoint
                if num_items > 100000:
                    feedback.pushInfo(f"  Large request detected ({num_items} items). Falling back to 'timeseries' endpoint...")
                    ensure_preflight()
                    
                    req_params_ts = {
                        "location": {"longitude": best_lon, "latitude": best_lat},
                        "date":     [f"{start_date_str}/{end_date_str}"],
                        "variable": variables,
                    }
                    if len(times) < 24:
                        req_params_ts["time"] = times
                    
                    c.retrieve('reanalysis-era5-single-levels-timeseries', req_params_ts, nc_file)
                    
                else:
                    try:
                        c.retrieve('reanalysis-era5-single-levels', req_params, nc_file)
                    except Exception as e:
                        # Fallback condition in case API hits an arbitrary internal size/memory limit
                        if "large" in str(e).lower() or "limit" in str(e).lower() or "size" in str(e).lower():
                            feedback.pushWarning(f"  Standard limit reached ({str(e)}). Falling back to 'timeseries' endpoint...")
                            ensure_preflight()
                            
                            req_params_ts = {
                                "location": {"longitude": best_lon, "latitude": best_lat},
                                "date":     [f"{start_date_str}/{end_date_str}"],
                                "variable": variables,
                            }
                            if len(times) < 24:
                                req_params_ts["time"] = times
                                
                            c.retrieve('reanalysis-era5-single-levels-timeseries', req_params_ts, nc_file)
                        else:
                            raise e

            except Exception as e:
                sys.stdout, sys.stderr = old_out, old_err
                feedback.pushWarning(f"API download failed for '{pt_label}': {e}")
                continue
            finally:
                sys.stdout, sys.stderr = old_out, old_err

            if feedback.isCanceled():
                return {}

            # ---- Extract data --------------------------------------------
            feedback.pushInfo("  Extracting data...")
            try:
                extract_res = self._extract_dataframe(nc_file, lat, lon, save_dir, safe_name, feedback)
                if isinstance(extract_res, tuple) and len(extract_res) == 3:
                    df, extracted_lat, extracted_lon = extract_res
                else:
                    df = extract_res
                    extracted_lat, extracted_lon = lat, lon
            except Exception as e:
                feedback.pushWarning(f"  Data extraction failed for '{pt_label}': {e}")
                continue

            if df is None or df.empty:
                feedback.pushWarning(f"  No data extracted for '{pt_label}'. Skipping.")
                if df is not None:
                    feedback.pushWarning(f"  Columns found were: {list(df.columns)}")
                continue

            # Use the actual coordinates (snapped if applicable)
            out_lat, out_lon = extracted_lat, extracted_lon
            
            # Rebuild safe_name for output files so it reflects the actual coordinates downloaded
            base_label = "".join(c if c.isalnum() or c in "-_." else "_" for c in pt_label)
            out_coord_suffix = f"_{abs(out_lat):.4f}{'N' if out_lat>=0 else 'S'}_{abs(out_lon):.4f}{'E' if out_lon>=0 else 'W'}"
            out_safe_name = base_label + out_coord_suffix

            # ---- Rename & derive -----------------------------------------
            df = df.rename(columns={k: v for k, v in RENAME_MAP.items() if k in df.columns})

            u10_col = '10m_u_component_of_wind [m/s] (u10)'
            v10_col = '10m_v_component_of_wind [m/s] (v10)'
            if u10_col in df.columns and v10_col in df.columns:
                df['wind_speed [m/s] (wspd)'] = np.sqrt(df[u10_col]**2 + df[v10_col]**2)
                # Meteorological convention for wind direction (from which it blows)
                df['wind_direction [deg] (wdir)'] = (
                    270 - np.degrees(np.arctan2(df[v10_col], df[u10_col]))
                ) % 360

            # ---- Trim to requested date range ----------------------------
            req_start = pd.to_datetime(start_date_str)
            req_end   = pd.to_datetime(end_date_str) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
            
            # Ensure timezones are removed to prevent tz-naive vs tz-aware comparison crashes
            if isinstance(df.index, pd.DatetimeIndex):
                df.index = df.index.tz_localize(None)
                df = df[(df.index >= req_start) & (df.index <= req_end)]
            else:
                df['time'] = pd.to_datetime(df['time']).dt.tz_localize(None)
                df = df[(df['time'] >= req_start) & (df['time'] <= req_end)]

            # ---- Save per-point CSV / Excel / TPAR -------------------------
            # Insert coordinate columns before exporting
            if 'Longitude' not in df.columns:
                df.insert(0, 'Longitude', out_lon)
            if 'Latitude' not in df.columns:
                df.insert(0, 'Latitude', out_lat)

            csv_path = os.path.join(save_dir, f"wave_data_{out_safe_name}.csv")
            df.to_csv(csv_path)
            feedback.pushInfo(f"  Saved CSV → {csv_path}")
            
            try:
                excel_path = os.path.join(save_dir, f"wave_data_{out_safe_name}.xlsx")
                df.to_excel(excel_path)
                feedback.pushInfo(f"  Saved Excel → {excel_path}")
            except Exception as e:
                feedback.pushInfo(f"  Could not save Excel, CSV is available.")
            
            if gen_timeseries:
                self._plot_interactive_timeseries(df, save_dir, out_safe_name, feedback)

            hs_col  = 'significant_height_of_combined_wind_waves_and_swell [m] (swh)'
            tp_col  = 'peak_wave_period [s] (pp1d)'
            tm_col  = 'mean_wave_period [s] (mwp)'
            dir_col = 'mean_wave_direction [deg] (mwd)'

            if hs_col in df.columns and (tp_col in df.columns or tm_col in df.columns) and dir_col in df.columns:
                period_col = tp_col if tp_col in df.columns else tm_col
                tpar_path = os.path.join(save_dir, f"boundary_{out_safe_name}.tpar")
                with open(tpar_path, 'w') as f:
                    f.write('TPAR\n')
                    for ts, row in df.iterrows():
                        t_str = ts.strftime('%Y%m%d.%H%M') if hasattr(ts, 'strftime') else str(ts)
                        f.write(
                            f"{t_str} {row[hs_col]:.2f} {row[period_col]:.2f} "
                            f"{row[dir_col]:.2f} 20.0\n"
                        )
                feedback.pushInfo(f"  Saved TPAR → {tpar_path}")

            # ---- Requirement 4: Create memory vector layer ---------------
            layer_result = self._build_memory_layer(df, out_lon, out_lat, pt_label, feedback)
            if layer_result is None or layer_result[0] is None:
                continue
            layer, wave_fld, wind_fld = layer_result

            # Generate Roses
            rose_path = None
            if gen_waverose:
                dir_c = dir_col if dir_col in df.columns else ('wind_direction [deg] (wdir)' if 'wind_direction [deg] (wdir)' in df.columns else None)
                hs_c = hs_col if hs_col in df.columns else ('wind_speed [m/s] (wspd)' if 'wind_speed [m/s] (wspd)' in df.columns else None)
                if hs_c and dir_c:
                    rose_path = self._plot_rose(df, save_dir, out_safe_name, hs_c, dir_c, 'waverose', feedback)

            wind_rose_path = None
            if gen_windrose:
                wind_dir_c = 'wind_direction [deg] (wdir)'
                wind_spd_c = 'wind_speed [m/s] (wspd)'
                if wind_spd_c in df.columns and wind_dir_c in df.columns:
                    wind_rose_path = self._plot_rose(df, save_dir, out_safe_name, wind_spd_c, wind_dir_c, 'windrose', feedback)

            # Apply Symbology (Image if Rose generated, else Arrow)
            if rose_path and os.path.exists(rose_path):
                self._apply_image_symbology(layer, rose_path, feedback)
            elif wind_rose_path and os.path.exists(wind_rose_path):
                self._apply_image_symbology(layer, wind_rose_path, feedback)
            else:
                self._apply_arrow_symbology(layer, wave_fld, wind_fld, feedback)

            # ---- Requirement 5: Max Hs stats + labeling ------------------
            label_str = self._apply_labels(layer, df, hs_col, tp_col, tm_col, dir_col, feedback)
            feedback.pushInfo(f"  Label string built: {label_str}")

            # ---- Add to QGIS project -------------------------------------
            QgsProject.instance().addMapLayer(layer)
            created_layers.append(layer.id())
            feedback.pushInfo(f"  Layer '{pt_label}' generated & added to QGIS.")

        feedback.setProgress(100)
        feedback.pushInfo(f"\nDone. {len(created_layers)} layer(s) successfully processed.")

        return {self.OUTPUT_DIR: save_dir}

    # ================================================================
    # Helper: extract DataFrame from downloaded file
    # ================================================================
    def _extract_dataframe(self, nc_file, lat, lon, save_dir, safe_name, feedback):
        import xarray as xr
        import pandas as pd
        import zipfile
        import glob

        actual_lat = lat
        actual_lon = lon

        def _read_data(file_path):
            nonlocal actual_lat, actual_lon
            df_part = pd.DataFrame()
            try:
                # Try reading as NetCDF first
                ds = xr.open_dataset(file_path, engine='netcdf4')
                has_lat = 'latitude' in ds.dims and ds.dims['latitude'] > 1
                has_lon = 'longitude' in ds.dims and ds.dims['longitude'] > 1
                if has_lat or has_lon:
                    ds_pt = ds.sel(latitude=lat, longitude=lon, method='nearest')
                    
                    # If the selected point has NaN for wave data (e.g. on land), find the nearest valid point
                    wave_vars_to_check = ['swh', 'significant_height_of_combined_wind_waves_and_swell']
                    wave_var = next((v for v in wave_vars_to_check if v in ds.data_vars), None)
                    
                    if wave_var and ds_pt[wave_var].isnull().all().item():
                        try:
                            mean_wave = ds[wave_var].mean(dim=[d for d in ds[wave_var].dims if d not in ['latitude', 'longitude']], skipna=False)
                            df_grid = mean_wave.to_dataframe().reset_index()
                            df_valid = df_grid.dropna(subset=[wave_var])
                            if not df_valid.empty:
                                df_valid['dist_sq'] = (df_valid['latitude'] - lat)**2 + (df_valid['longitude'] - lon)**2
                                best_row = df_valid.loc[df_valid['dist_sq'].idxmin()]
                                best_lat, best_lon = best_row['latitude'], best_row['longitude']
                                ds_pt = ds.sel(latitude=best_lat, longitude=best_lon, method='nearest')
                                feedback.pushInfo(f"    Point is on land (no wave data). Selected nearest offshore point at Lat={best_lat:.4f}, Lon={best_lon:.4f}")
                        except Exception as e:
                            feedback.pushWarning(f"    Failed to find nearest offshore point: {e}")
                else:
                    ds_pt = ds.squeeze()
                
                if 'latitude' in ds_pt.coords:
                    actual_lat = float(ds_pt.coords['latitude'].values)
                if 'longitude' in ds_pt.coords:
                    actual_lon = float(ds_pt.coords['longitude'].values)
                
                df_part = ds_pt.to_dataframe().reset_index()
            except Exception:
                # Fallback to reading as CSV (typical for ARCO timeseries endpoint)
                try:
                    df_part = pd.read_csv(file_path, comment='#')
                    if 'latitude' in df_part.columns and not df_part['latitude'].isnull().all():
                        actual_lat = float(df_part['latitude'].dropna().iloc[0])
                    if 'longitude' in df_part.columns and not df_part['longitude'].isnull().all():
                        actual_lon = float(df_part['longitude'].dropna().iloc[0])
                except Exception as e:
                    feedback.pushWarning(f"    Failed to read file {file_path}: {e}")
                    return pd.DataFrame()

            # Clean columns of trailing spaces
            df_part.columns = [str(c).strip() for c in df_part.columns]

            # Standardize time column name (checking various known formats)
            for alias in ('valid_time', 'datetime', 'valid_datetime', 'date', 'time'):
                for col in df_part.columns:
                    if col.lower() == alias and 'time' not in df_part.columns:
                        df_part.rename(columns={col: 'time'}, inplace=True)

            if 'time' in df_part.columns:
                df_part['time'] = pd.to_datetime(df_part['time'], errors='coerce')

            drop = {'latitude', 'longitude', 'number', 'step', 'surface', 'expver'}
            df_part = df_part[[c for c in df_part.columns if c.lower() not in drop]]
            return df_part

        df = None

        if zipfile.is_zipfile(nc_file):
            extract_dir = os.path.join(save_dir, f'era5_extracted_{safe_name}')
            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(nc_file, 'r') as zf:
                zf.extractall(extract_dir)
                
            # Deep search for any CSV or NC files extracted
            all_files = []
            for root, _, files in os.walk(extract_dir):
                for f in files:
                    if f.endswith('.nc') or f.endswith('.csv'):
                        all_files.append(os.path.join(root, f))
            
            feedback.pushInfo(f"    Extracted {len(all_files)} files from ZIP archive.")
            
            for fp in all_files:
                part = _read_data(fp)
                if not part.empty:
                    if df is None:
                        df = part
                    else:
                        part = part.drop_duplicates(subset=['time'])
                        df = pd.merge(df, part, on='time', how='outer')
        else:
            df = _read_data(nc_file)

        if df is not None and not df.empty and 'time' in df.columns:
            df = df.drop_duplicates(subset=['time'])
            df.sort_values('time', inplace=True)
            df.set_index('time', inplace=True)
            df.dropna(how='all', inplace=True)
            feedback.pushInfo(f"    Data extracted successfully. Columns detected: {list(df.columns)}")
        else:
            feedback.pushWarning("    Could not parse time index properly from data.")

        return df, actual_lat, actual_lon

    # ================================================================
    # Helper: build a QGIS memory vector layer from DataFrame
    # ================================================================
    def _build_memory_layer(self, df, lon, lat, label, feedback):
        import pandas as pd

        # Build field list
        fields = []
        fields.append(QgsField("timestamp", QVariant.String, len=30))

        col_field_map = {}
        for col in df.columns:
            import re
            match = re.search(r'\((.*?)\)', col)
            if match:
                safe_col = match.group(1)[:10]
            else:
                safe_col = col[:10]

            base_col = safe_col
            counter = 1
            while safe_col in [f.name() for f in fields]:
                safe_col = f"{base_col[:8]}_{counter}"
                counter += 1

            if 'm/s' in col or '[m]' in col or '[s]' in col or 'cdww' in col or '[K]' in col or '[Pa]' in col:
                fld = QgsField(safe_col, QVariant.Double, len=20, prec=4)
            elif '[deg]' in col:
                fld = QgsField(safe_col, QVariant.Double, len=20, prec=2)
            else:
                fld = QgsField(safe_col, QVariant.Double, len=20, prec=4)
            fields.append(fld)
            col_field_map[col] = safe_col

        layer = QgsVectorLayer("Point?crs=EPSG:4326", label, "memory")
        if not layer.isValid():
            feedback.pushWarning(f"  Could not create memory layer for '{label}'.")
            return None, None, None

        provider = layer.dataProvider()
        provider.addAttributes(fields)
        layer.updateFields()

        geom = QgsGeometry.fromPointXY(QgsPointXY(lon, lat))

        feats = []
        for ts, row in df.iterrows():
            feat = QgsFeature(layer.fields())
            feat.setGeometry(geom)
            ts_str = ts.strftime('%Y-%m-%d %H:%M') if hasattr(ts, 'strftime') else str(ts)
            feat.setAttribute("timestamp", ts_str)
            for col, safe_col in col_field_map.items():
                val = row.get(col)
                if pd.isna(val):
                    feat.setAttribute(safe_col, None)
                else:
                    feat.setAttribute(safe_col, float(val))
            feats.append(feat)

        provider.addFeatures(feats)
        layer.updateExtents()
        
        wave_fld = col_field_map.get('mean_wave_direction [deg] (mwd)')
        wind_fld = col_field_map.get('wind_direction [deg] (wdir)')
        return layer, wave_fld, wind_fld

    # ================================================================
    # Helper: calculate max Hs stats and apply QGIS labels
    # ================================================================
    def _apply_labels(self, layer, df, hs_col, tp_col, tm_col, dir_col, feedback):
        import pandas as pd

        label_str = "No Hs data"

        if hs_col in df.columns and not df[hs_col].dropna().empty:
            max_hs = df[hs_col].max()
            ts_max = df[hs_col].idxmax()
            
            period_val = float('nan')
            period_lbl = "Tp"
            if tp_col in df.columns and pd.notna(df.loc[ts_max, tp_col]):
                period_val = df.loc[ts_max, tp_col]
            elif tm_col in df.columns and pd.notna(df.loc[ts_max, tm_col]):
                period_val = df.loc[ts_max, tm_col]
                period_lbl = "Tm"
                
            dir_val = df.loc[ts_max, dir_col] if dir_col in df.columns else float('nan')

            p_str  = f"{period_val:.1f}"  if pd.notna(period_val)  else "N/A"
            dir_str = f"{dir_val:.0f}" if pd.notna(dir_val) else "N/A"

            label_str = f"Max Hs: {max_hs:.1f}m | {period_lbl}: {p_str}s | Dir: {dir_str}°"

        # Configure QGIS label settings
        lyr_settings = QgsPalLayerSettings()
        
        # We use an expression to ensure that ONLY the first feature of the timeseries is labeled. 
        lyr_settings.fieldName = f"if($id = 1, '{label_str}', '')"
        lyr_settings.isExpression = True

        # Text format
        txt_fmt = QgsTextFormat()
        font = QFont("Arial", 9)
        font.setBold(True)
        txt_fmt.setFont(font)
        txt_fmt.setSize(9)
        txt_fmt.setColor(QColor("#003366"))

        # White buffer/halo
        buf = QgsTextBufferSettings()
        buf.setEnabled(True)
        buf.setSize(1.5)
        buf.setColor(QColor("white"))
        txt_fmt.setBuffer(buf)

        lyr_settings.setFormat(txt_fmt)
        lyr_settings.placement = Qgis.LabelPlacement.OverPoint

        labeling = QgsVectorLayerSimpleLabeling(lyr_settings)
        layer.setLabeling(labeling)
        layer.setLabelsEnabled(True)
        layer.triggerRepaint()

        return label_str

    # ================================================================
    # Helper: Apply vector layer arrow symbology
    # ================================================================
    def _apply_arrow_symbology(self, layer, wave_fld, wind_fld, feedback):
        from qgis.core import (
            QgsSingleSymbolRenderer, 
            QgsMarkerSymbol, 
            QgsSymbolLayer, 
            QgsProperty,
            QgsSymbol
        )
        
        if not wave_fld and not wind_fld:
            return
            
        symbol = QgsMarkerSymbol()
        symbol.deleteSymbolLayer(0) # Remove default simple marker
        
        # Add Wind Arrow (Orange, slightly smaller)
        if wind_fld:
            wind_sym = QgsMarkerSymbol.createSimple({
                'name': 'filled_arrowhead',
                'color': '255,153,51,255',
                'size': '4',
                'outline_color': '0,0,0,255'
            })
            if wind_sym and wind_sym.symbolLayerCount() > 0:
                wind_layer = wind_sym.symbolLayer(0)
                # Add 180 here so the map arrow points WHERE it is going, preserving raw data in the table
                wind_layer.setDataDefinedProperty(QgsSymbolLayer.PropertyAngle, QgsProperty.fromExpression(f'("{wind_fld}" + 180) % 360'))
                symbol.appendSymbolLayer(wind_layer.clone())
                
        # Add Wave Arrow (Blue, standard size)
        if wave_fld:
            wave_sym = QgsMarkerSymbol.createSimple({
                'name': 'arrow',
                'color': '0,102,204,255',
                'size': '6',
                'outline_color': '0,0,0,255'
            })
            if wave_sym and wave_sym.symbolLayerCount() > 0:
                wave_layer = wave_sym.symbolLayer(0)
                # Add 180 here so the map arrow points WHERE it is going, preserving raw data in the table
                wave_layer.setDataDefinedProperty(QgsSymbolLayer.PropertyAngle, QgsProperty.fromExpression(f'("{wave_fld}" + 180) % 360'))
                symbol.appendSymbolLayer(wave_layer.clone())

        if symbol.symbolLayerCount() > 0:
            renderer = QgsSingleSymbolRenderer(symbol)
            layer.setRenderer(renderer)
            layer.triggerRepaint()
            
    # ================================================================
    # Helper: Apply Image Symbology (Wave Rose SVG)
    # ================================================================
    def _apply_image_symbology(self, layer, image_path, feedback):
        from qgis.core import (
            QgsSvgMarkerSymbolLayer,
            QgsMarkerSymbol,
            QgsRuleBasedRenderer
        )
        
        svg_layer = QgsSvgMarkerSymbolLayer(image_path)
        svg_layer.setSize(35) # Size in millimeters on the map
        
        symbol = QgsMarkerSymbol()
        symbol.changeSymbolLayer(0, svg_layer)
        
        # Render the image on the very first feature to prevent stacking
        root_rule = QgsRuleBasedRenderer.Rule(None)
        rule = QgsRuleBasedRenderer.Rule(symbol, 0, 0, filterExp="$id = 1", label="Wave Rose")
        root_rule.appendChild(rule)
        
        renderer = QgsRuleBasedRenderer(root_rule)
        layer.setRenderer(renderer)
        layer.triggerRepaint()

    # ================================================================
    # Helper: Plot Wave Rose (Raw Meteorological Data & Exact Legend)
    # ================================================================
    def _plot_rose(self, df, save_dir, safe_name, mag_col, dir_col, prefix, feedback):
        try:
            import numpy as np
            import matplotlib.pyplot as plt
            import matplotlib.cm as cm
            
            df_valid = df.dropna(subset=[mag_col, dir_col])
            if df_valid.empty:
                feedback.pushWarning(f"    Not enough data to plot {prefix}.")
                return None
                
            val = df_valid[mag_col].values
            
            # Use raw ERA5 data directly (Meteorological: Coming From)
            dir_from = df_valid[dir_col].values 
            
            num_sectors = 16
            sector_edges = np.linspace(0, 360, num_sectors + 1)
            
            # -------------------------------------------------------------
            # EXACT DYNAMIC BINNING ALGORITHM
            # -------------------------------------------------------------
            max_val = np.max(val)
            if max_val <= 0:
                max_val = 1.0  # Prevent division by zero
                
            num_bins = 5 # Number of color categories
            step = max_val / num_bins
            
            bins = [0]
            labels = []
            
            for i in range(num_bins):
                start_val = bins[-1]
                end_val = start_val + step
                
                # If it's the last bin, label it to show the exact max value
                if i == num_bins - 1:
                    bins.append(np.inf) 
                    labels.append(f"{start_val:.2f} - {max_val:.2f}")
                else:
                    bins.append(end_val)
                    labels.append(f"{start_val:.2f} - {end_val:.2f}")

            # -------------------------------------------------------------
            
            dir_shifted = (dir_from + 11.25) % 360
            H, _, _ = np.histogram2d(dir_shifted, val, bins=[sector_edges, bins])
            H = H / len(val) * 100 # percentage
            
            fig, ax = plt.subplots(figsize=(8, 8), subplot_kw={'projection': 'polar'})
            ax.set_theta_zero_location('N')
            ax.set_theta_direction(-1) # Clockwise
            
            theta = np.radians(np.linspace(0, 360, num_sectors, endpoint=False))
            width = np.radians(22.5) * 0.9
            bottoms = np.zeros(num_sectors)
            colors = cm.viridis(np.linspace(0.2, 1, len(bins)-1))
            
            for i in range(len(bins) - 1):
                ax.bar(theta, H[:, i], width=width, bottom=bottoms, color=colors[i], edgecolor='white', label=labels[i])
                bottoms += H[:, i]
                
            short_title = mag_col.split(' [')[0] if ' [' in mag_col else mag_col
            ax.legend(title=short_title, loc='center left', bbox_to_anchor=(1.1, 0.5))
            
            dir_short = dir_col.split(' [')[0] if ' [' in dir_col else dir_col
            
            # Explicitly state Meteorological format in the title
            ax.set_title(f"Directional Distribution (Meteorological: Coming From)\n{dir_short}\n{safe_name}", pad=20)
            
            max_freq = np.max(bottoms)
            if max_freq > 0:
                ticks = np.linspace(0, max_freq, 5)
                ax.set_yticks(ticks)
                ax.set_yticklabels([f"{t:.1f}%" for t in ticks], color='gray', size=8)
            
            out_path = os.path.join(save_dir, f"{prefix}_{safe_name}.svg")
            plt.savefig(out_path, format='svg', bbox_inches='tight')
            plt.close(fig)
            feedback.pushInfo(f"  Saved Rose Plot → {out_path}")
            return out_path
            
        except ImportError:
            feedback.pushWarning(f"  'matplotlib' library not installed. Cannot generate {prefix}.")
            return None
        except Exception as e:
            feedback.pushWarning(f"  Failed to plot {prefix}: {e}")
            return None

    # ================================================================
    # Helper: Plot Interactive Timeseries
    # ================================================================
    def _plot_interactive_timeseries(self, df, save_dir, safe_name, feedback):
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
            
            # Select numerical columns to plot (exclude potential non-numeric or unwanted columns)
            cols_to_plot = [c for c in df.select_dtypes(include=['number']).columns if c not in ['longitude', 'latitude']]
            if not cols_to_plot:
                return
                
            fig = make_subplots(rows=len(cols_to_plot), cols=1, shared_xaxes=True, vertical_spacing=0.02)
            
            for i, col in enumerate(cols_to_plot):
                fig.add_trace(go.Scatter(
                    x=df.index, 
                    y=df[col], 
                    mode='lines',
                    name=col.split(' [')[0] if ' [' in col else col,
                    hovertemplate='%{x}<br>%{y}'
                ), row=i+1, col=1)
                
                # Add y-axis label
                y_label = col.split('(')[-1].replace(')', '') if '(' in col else col
                fig.update_yaxes(title_text=y_label, row=i+1, col=1)
                
            fig.update_layout(
                title=f"Interactive Timeseries Data: {safe_name}",
                height=max(400, 250 * len(cols_to_plot)),
                hovermode="x unified",
                showlegend=False
            )
            
            out_path = os.path.join(save_dir, f"timeseries_{safe_name}.html")
            fig.write_html(out_path)
            feedback.pushInfo(f"  Saved Interactive Timeseries → {out_path}")
            return out_path
        except ImportError:
            feedback.pushWarning("  'plotly' library not installed. Cannot generate interactive timeseries. Run: python -m pip install plotly")
        except Exception as e:
            feedback.pushWarning(f"  Failed to plot Interactive Timeseries: {e}")
