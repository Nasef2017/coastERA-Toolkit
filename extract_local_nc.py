import tkinter as tk
from tkinter import filedialog, messagebox
import xarray as xr
import pandas as pd
import matplotlib.pyplot as plt
import os
import numpy as np

def extract_nc():
    root = tk.Tk()
    root.withdraw() # Hide main window

    file_path = filedialog.askopenfilename(
        title="Select ERA5 .nc File",
        filetypes=[("NetCDF Files", "*.nc"), ("All Files", "*.*")]
    )

    if not file_path:
        return

    save_dir = os.path.dirname(file_path)
    
    try:
        ds = xr.open_dataset(file_path, engine='netcdf4')
        ds_point = ds.squeeze()
        df = ds_point.to_dataframe().reset_index()

        if 'valid_time' in df.columns and 'time' not in df.columns:
            df.rename(columns={'valid_time': 'time'}, inplace=True)
        if 'time' in df.columns and str(df['time'].dtype) == 'object':
            df['time'] = pd.to_datetime(df['time'])

        rename_map = {
            'swh': 'Hs (m)', 'pp1d': 'Tp (s)', 'mwd': 'Dir (° Met, True North)',
            'mwp': 'Tm (s)', 'shww': 'Hs_wind (m)', 'mpww': 'Tm_wind (s)',
            'mdww': 'Dir_wind (° Met, True North)', 'shts': 'Hs_swell (m)',
            'mpts': 'Tm_swell (s)', 'mdts': 'Dir_swell (° Met, True North)',
            'cdww': 'Cd', 'u10': 'U10 (m/s)', 'v10': 'V10 (m/s)',
            'si10': 'WindSpd (m/s)', 'dwi': 'WindDir (° Met, True North)'
        }
        
        current_rename = {k: v for k, v in rename_map.items() if k in df.columns}
        df.rename(columns=current_rename, inplace=True)
        
        cols_to_keep = ['time'] + list(current_rename.values())
        for col in df.columns:
            if col not in cols_to_keep and col not in ['latitude', 'longitude', 'number', 'step', 'surface']:
                cols_to_keep.append(col)
                
        df = df[[c for c in cols_to_keep if c in df.columns]]
        df.set_index('time', inplace=True)
        df.dropna(inplace=True)

        if 'U10 (m/s)' in df.columns and 'V10 (m/s)' in df.columns:
            df['WindSpd (m/s)'] = np.sqrt(df['U10 (m/s)']**2 + df['V10 (m/s)']**2)
            df['WindDir (° Met, True North)'] = (270 - np.degrees(np.arctan2(df['V10 (m/s)'], df['U10 (m/s)']))) % 360

        # Create CSV
        csv_path = os.path.join(save_dir, 'extracted_data.csv')
        with open(csv_path, 'w', encoding='utf-8') as f:
            f.write("# ERA5 Timeseries Data Extract\n")
            f.write("# Data Source: Copernicus Climate Data Store (ERA5)\n")
            f.write("# Abbreviations:\n")
            for k, v in current_rename.items():
                f.write(f"#   {v} = {k}\n")
            if 'WindSpd (m/s)' in df.columns: f.write("#   WindSpd (m/s) = si10 / Derived\n")
            if 'WindDir (° Met, True North)' in df.columns: f.write("#   WindDir (° Met, True North) = dwi / Derived\n")
            f.write("#\n")
        df.to_csv(csv_path, mode='a')
        print(f"Saved CSV: {csv_path}")

        # Wave Rose
        if all(v in df.columns for v in ['Hs (m)', 'Tp (s)', 'Dir (° Met, True North)']):
            try:
                from windrose import WindroseAxes
                import matplotlib.cm as cm
                fig = plt.figure(figsize=(10, 8))
                rect = [0.1, 0.1, 0.6, 0.8]
                ax = WindroseAxes(fig, rect)
                fig.add_axes(ax)
                ax.bar(df['Dir (° Met, True North)'], df['Hs (m)'], normed=True, opening=0.8, edgecolor='white', cmap=cm.viridis)
                ax.set_title('Wave Rose (ERA5)')
                ax.set_legend(title="Hs (m)", bbox_to_anchor=(1.1, 0.5), loc="center left")
                
                fig.text(0.02, 0.02, "Data Source: Copernicus Climate Data Store (ERA5)", fontsize=10, style='italic', color='gray')
                abbrev_text = "Abbreviations:\nHs : Significant Wave Height (m)\nDir : Mean Wave Direction (° Met)\n      (True North, Coming From)"
                fig.text(0.75, 0.2, abbrev_text, fontsize=10, bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="gray", alpha=0.9))
                
                p = os.path.join(save_dir, 'wave_rose.png')
                plt.savefig(p, dpi=300, bbox_inches='tight')
                plt.close(fig)
                print(f"Saved Wave Rose: {p}")
            except ImportError:
                print("windrose not installed.")

        # Wind Rose
        if all(v in df.columns for v in ['WindSpd (m/s)', 'WindDir (° Met, True North)']):
            try:
                from windrose import WindroseAxes
                import matplotlib.cm as cm
                fig = plt.figure(figsize=(10, 8))
                rect = [0.1, 0.1, 0.6, 0.8]
                ax = WindroseAxes(fig, rect)
                fig.add_axes(ax)
                ax.bar(df['WindDir (° Met, True North)'], df['WindSpd (m/s)'], normed=True, opening=0.8, edgecolor='white', cmap=cm.viridis)
                ax.set_title('Wind Rose (ERA5)')
                ax.set_legend(title="WindSpd (m/s)", bbox_to_anchor=(1.1, 0.5), loc="center left")
                
                fig.text(0.02, 0.02, "Data Source: Copernicus Climate Data Store (ERA5)", fontsize=10, style='italic', color='gray')
                abbrev_text = "Abbreviations:\nWindSpd : Wind Speed (m/s)\nWindDir : Wind Direction (° Met)\n          (True North, Coming From)"
                fig.text(0.75, 0.2, abbrev_text, fontsize=10, bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="gray", alpha=0.9))
                
                p = os.path.join(save_dir, 'wind_rose.png')
                plt.savefig(p, dpi=300, bbox_inches='tight')
                plt.close(fig)
                print(f"Saved Wind Rose: {p}")
            except ImportError:
                pass
                
        messagebox.showinfo("Success", "Extraction and plotting complete!")
    except Exception as e:
        messagebox.showerror("Error", str(e))

if __name__ == "__main__":
    extract_nc()
