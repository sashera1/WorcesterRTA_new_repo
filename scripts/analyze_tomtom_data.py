#def time_penalty_walking():
    #avg speed: 1.42 meters/sec standard deviation: .24
    #src: AASignalisedCrossingsReport.pdf

import csv
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from collections import defaultdict

def calculate_distance_decay_matrix(filepath, distance_ranges):
    """
    Parses a TomTom O/D matrix and aggregates trips by origin and destination distance rings.
    
    :param filepath: Path to the TomTom CSV file.
    :param distance_ranges: List of ring boundaries (e.g., [800, 600, 400, 200, 100, 0])
    :return: A pandas DataFrame representing the aggregated ring-to-ring trip matrix.
    """
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
                try:
                    # Switched to int() per your request, assuming whole numbers
                    # (Used int(float()) just in case TomTom outputs "6.0" as a string)
                    trips = int(float(trips_str)) 
                    matrix_sums[(orig_band, dest_band)] += trips
                except ValueError:
                    continue 
                    
    # Initialize DataFrame with ints
    df_matrix = pd.DataFrame(index=bands, columns=bands).fillna(0).astype(int)
    
    for (o_band, d_band), total_trips in matrix_sums.items():
        df_matrix.at[o_band, d_band] = total_trips
        
    return df_matrix

# ==========================================
# Main Execution and Visualization
# ==========================================
if __name__ == "__main__":
    csv_file_path = "data/processed/tomtom_output/buffered_corridors_split_by_tier_and_nearest_stop.csv" 
    
    radii = [800, 600, 400, 200, 100, 0]
    
    print("Calculating matrix...")
    try:
        decay_matrix = calculate_distance_decay_matrix(csv_file_path, radii)
        print("--- Aggregated Ring-to-Ring Commuter Flow ---")
        print(decay_matrix)
        
        # --- Matplotlib 2D Heatmap Grid ---
        # Set up the figure
        fig, ax = plt.subplots(figsize=(8, 6))
        
        # Create the White-to-Red heatmap
        cax = ax.imshow(decay_matrix.values, cmap="Reds", aspect="auto")
        ax.invert_yaxis()
        
        # Add the colorbar legend
        cbar = fig.colorbar(cax)
        cbar.set_label('Total Car Trips', rotation=270, labelpad=15, fontsize=12)
        
        # Set up the axis labels (the distance bands)
        ax.set_xticks(np.arange(len(decay_matrix.columns)))
        ax.set_yticks(np.arange(len(decay_matrix.index)))
        ax.set_xticklabels(decay_matrix.columns, fontsize=10)
        ax.set_yticklabels(decay_matrix.index, fontsize=10)
        
        # Rotate X-axis labels so they are easy to read
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")
        
        # Loop over the data dimensions and create text annotations inside the grid cells
        # This writes the integer numbers right on top of the colors
        for i in range(len(decay_matrix.index)):
            for j in range(len(decay_matrix.columns)):
                val = decay_matrix.values[i, j]
                # If the cell is super dark red, use white text. Otherwise, black text.
                text_color = "white" if val > (decay_matrix.values.max() / 2) else "black"
                ax.text(j, i, str(val), ha="center", va="center", color=text_color, fontsize=11, fontweight='bold')
        
        ax.set_title("All trips by distance from nearest stops, Monday-Thursday 8am-5pm", fontsize=12, pad=20, fontweight='bold')
        ax.set_xlabel("Destination Distance Band", fontsize=12, fontweight='bold')
        ax.set_ylabel("Origin Distance Band", fontsize=12, fontweight='bold')
        
        plt.tight_layout() # Ensures labels don't get cut off
        
        # This will pop open the window with your graph! 
        # You can click the "Save" icon in the window to instantly save it as an image for your presentation.
        plt.show()

    except FileNotFoundError:
        print(f"Error: Could not find the file at {csv_file_path}. Please update the file path.")