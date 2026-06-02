#transparency NOTE: this script was (mostly) generated with AI (gemini Pro)

import matplotlib.pyplot as plt
import csv
import json

def visualize(csv_paths_by_color:dict, municipal_boundary : str | None = None ):
    plt.figure(figsize=(10, 8))
    points_plotted = False

    if municipal_boundary:
        try:
            with open(municipal_boundary, 'r', encoding='utf-8') as f:
                boundary_json = json.load(f)
            # GeoJSON Polygons store coordinates in an array where the 0th element is the exterior ring
            coordinates = boundary_json["features"][0]["geometry"]["coordinates"][0]
            
            # Separate into X (longitude) and Y (latitude)
            boundary_longs = [coord[0] for coord in coordinates]
            boundary_lats = [coord[1] for coord in coordinates]
            
            # Plot the boundary as a thin red line
            plt.plot(boundary_longs, boundary_lats, color='red', linewidth=1, label="Worcester Boundary")
            points_plotted = True
        except (KeyError, IndexError) as e:
            print(f"Error extracting boundary coordinates: {e}")

    for color_name, file_path in csv_paths_by_color.items():
            
        lats = []
        lons = []
        
        # Read the CSV using the built-in csv module
        with open(file_path, mode='r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            
            for row in reader:
                try:
                    # Extract coordinates and ignore stop_id
                    lats.append(float(row['latitude']))
                    lons.append(float(row['longitude']))
                except (ValueError, KeyError):
                    # Skip rows that are missing latitude/longitude or have invalid data
                    continue
        
        if lats and lons:
            # Plot Longitude (X) and Latitude (Y)
            # Use the dictionary key as the color, converted to lowercase just in case
            plt.scatter(lons, lats, c=color_name.lower(), label=f"{color_name} Corridor", s=30, alpha=0.8)
            points_plotted = True

    if points_plotted:
        plt.xlabel("Longitude")
        plt.ylabel("Latitude")
        plt.title("Transit Stop Coordinates")
        
        # Set aspect ratio to 'equal' so the map doesn't stretch geographically
        plt.gca().set_aspect('equal', adjustable='datalim')
        
        plt.grid(True, linestyle='--', alpha=0.5)
        plt.legend()
        
        # Display the plot in a window
        plt.show()


to_visualize = {
    'Orange': "Orange_corridor_shared_stops.csv",
    'Blue': "Blue_corridor_shared_stops.csv",
    'Green': "Green_corridor_shared_stops.csv"
}

visualize(to_visualize, "worcester_municipal_boundary.geojson")


