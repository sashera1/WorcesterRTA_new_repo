#def time_penalty_walking():
    #avg speed: 1.42 meters/sec standard deviation: .24
    #src: AASignalisedCrossingsReport.pdf


import csv
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from collections import defaultdict

def calculate_distance_decay_matrix(filepath, distance_ranges, corridor_stops_csv=None):
   
    valid_stops = None
    if corridor_stops_csv:
        valid_stops = set()
        with open(corridor_stops_csv, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header and header[0].lower() != 'stop_id':
                valid_stops.add(header[0])
            for row in reader:
                if row:
                    valid_stops.add(row[0])
        print(f"Loaded {len(valid_stops)} valid stops from corridor CSV.")

    sorted_ranges = sorted(distance_ranges)
    bands = []
    for i in range(len(sorted_ranges) - 1):
        bands.append(f"{sorted_ranges[i]}-{sorted_ranges[i+1]}m")
        
    def extract_band(region_name):
        for band in bands:
            if region_name.endswith(f"_{band}"):
                return band
        return None

    matrix_sums = defaultdict(int)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader) 
        
        for row in reader:
            if len(row) < 3:
                continue
                
            orig = row[0]
            dest = row[1]
            trips_str = row[2]
            
            if "External" in orig or "External" in dest:
                continue
            if "TRANSITION_ZONE" in orig or "TRANSITION_ZONE" in dest:
                continue
                
            orig_band = extract_band(orig)
            dest_band = extract_band(dest)
            
            if orig_band and dest_band:
                
                if valid_stops is not None:
                    orig_stop_id = orig[: -(len(orig_band) + 1)] 
                    dest_stop_id = dest[: -(len(dest_band) + 1)]
                    
                    if orig_stop_id not in valid_stops or dest_stop_id not in valid_stops:
                        continue

                try:
                    trips = int(float(trips_str)) 
                    matrix_sums[(orig_band, dest_band)] += trips
                except ValueError:
                    continue 
                    
    # 4. Format into DataFrame
    df_matrix = pd.DataFrame(index=bands, columns=bands).fillna(0).astype(int)
    for (o_band, d_band), total_trips in matrix_sums.items():
        df_matrix.at[o_band, d_band] = total_trips
        
    return df_matrix

# ==========================================
# Main Execution and Visualization
# ==========================================
if __name__ == "__main__":
    
    tomtom_matrix_path = "path/to/your/tomtom_matrix.csv" 
    
    corridor_csv_path = "path/to/your/Orange_corridor_shared_stops.csv" 
    # ---------------------------------------------------------

    radii = [800, 600, 400, 200, 100, 0]
    
    print("Calculating matrix...")
    try:
        decay_matrix = calculate_distance_decay_matrix(tomtom_matrix_path, radii, corridor_stops_csv=corridor_csv_path)
        
        print("\n--- Aggregated Ring-to-Ring Commuter Flow ---")
        print(decay_matrix)
        
        fig, ax = plt.subplots(figsize=(8, 6))
        
        cax = ax.imshow(decay_matrix.values, cmap="Reds", aspect="auto")
        
        ax.invert_yaxis()
        
        cbar = fig.colorbar(cax)
        cbar.set_label('Total Car Trips', rotation=270, labelpad=15, fontsize=12)
        
        ax.set_xticks(np.arange(len(decay_matrix.columns)))
        ax.set_yticks(np.arange(len(decay_matrix.index)))
        ax.set_xticklabels(decay_matrix.columns, fontsize=10)
        ax.set_yticklabels(decay_matrix.index, fontsize=10)
        
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")
        
        for i in range(len(decay_matrix.index)):
            for j in range(len(decay_matrix.columns)):
                val = decay_matrix.values[i, j]
                text_color = "white" if val > (decay_matrix.values.max() / 2) else "black"
                ax.text(j, i, str(val), ha="center", va="center", color=text_color, fontsize=11, fontweight='bold')
        
        title = "O/D Trip Volume by Distance"
        if corridor_csv_path:
            title += "\n(Filtered to Specific Corridor)"
            
        ax.set_title(title, fontsize=14, pad=20, fontweight='bold')
        ax.set_xlabel("Destination Distance Band", fontsize=12, fontweight='bold')
        ax.set_ylabel("Origin Distance Band", fontsize=12, fontweight='bold')
        
        plt.tight_layout() 
        plt.show()

    except FileNotFoundError as e:
        print(f"Error: Could not find a file. Please double-check your file paths. \nDetails: {e}")



        




""" 
import csv
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from collections import defaultdict

def calculate_distance_decay_matrix(filepath, distance_ranges):
    
    sorted_ranges = sorted(distance_ranges)
    bands = []
    for i in range(len(sorted_ranges)- 1):
        bands.append(f"{sorted_ranges[i]}-{sorted_ranges[i+1]}m")
        
    def extract_band(region_name):
        for band in bands:
            if region_name.endswith(f"_{band}"):
                return band
        return None

    matrix_sums = defaultdict(int)
    
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader) 
        
        for row in reader:
            if len(row) < 3:
                continue
                
            orig = row[0]
            dest = row[1]
            trips_str = row[2]
            
            if "External" in orig or "External" in dest:
                continue
            if "TRANSITION_ZONE" in orig or "TRANSITION_ZONE" in dest:
                continue
                
            orig_band = extract_band(orig)
            dest_band = extract_band(dest)
            
            if orig_band and dest_band:
                try:

                    trips = int(float(trips_str)) 
                    matrix_sums[(orig_band, dest_band)] += trips
                except ValueError:
                    continue 
                    
    df_matrix = pd.DataFrame(index=bands, columns=bands).fillna(0).astype(int)
    
    for (o_band, d_band), total_trips in matrix_sums.items():
        df_matrix.at[o_band, d_band] = total_trips
        
    return df_matrix


if __name__ == "__main__":
    csv_file_path = "data/processed/tomtom_output/buffered_corridors_split_by_tier_and_nearest_stop.csv" 
    
    radii = [800, 600, 400, 200, 100, 0]
    
    try:
        decay_matrix = calculate_distance_decay_matrix(csv_file_path, radii)
        print("--- Aggregated Ring-to-Ring Commuter Flow ---")
        print(decay_matrix)
      
        fig, ax = plt.subplots(figsize=(8, 6))
        
        cax = ax.imshow(decay_matrix.values, cmap="Reds", aspect="auto")
        ax.invert_yaxis()
        
        cbar = fig.colorbar(cax)
        cbar.set_label('Total Car Trips', rotation=270, labelpad=15, fontsize=12)
        
        ax.set_xticks(np.arange(len(decay_matrix.columns)))
        ax.set_yticks(np.arange(len(decay_matrix.index)))
        ax.set_xticklabels(decay_matrix.columns, fontsize=10)
        ax.set_yticklabels(decay_matrix.index, fontsize=10)
        
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")
        
 
        for i in range(len(decay_matrix.index)):
            for j in range(len(decay_matrix.columns)):
                val = decay_matrix.values[i, j]
                text_color = "white" if val > (decay_matrix.values.max() / 2) else "black"
                ax.text(j, i, str(val), ha="center", va="center", color=text_color, fontsize=11, fontweight='bold')
        
        ax.set_title("All trips by distance from nearest stops, Monday-Thursday 8am-5pm", fontsize=12, pad=20, fontweight='bold')
        ax.set_xlabel("Destination Distance Band", fontsize=12, fontweight='bold')
        ax.set_ylabel("Origin Distance Band", fontsize=12, fontweight='bold')
        
        plt.tight_layout() #   dont want label cut off
       
        plt.show()

    except FileNotFoundError:
        print(f"Error: Could not find the file at {csv_file_path}. Please update the file path.")
        """