import matplotlib.pyplot as plt
import csv
import json
from src.toolkits.geometric_toolset import pad_boundry
from src.config import debug_mode

import matplotlib.colors as mcolors
import matplotlib.path as mpath
import matplotlib.patches as mpatches

#TODO LATER: refactor to visualize stops by corridor/route and polygons in general,
#and to be flexible about number of each kind of param
#and for label to be related to which things are being visualized, 
#and appropriate details, ie, if for area around corridor,
#label includes distance from stops, etc

def visualize_points(color, points_path, order=3):
    lats = []
    longs = []
    
    with open(points_path, mode='r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        
        for row in reader:
            try:
                lats.append(float(row['latitude']))
                longs.append(float(row['longitude']))
            except (ValueError, KeyError):
                if debug_mode:
                    print(f"skipped row while loading points for visualization")
                continue
    
    if lats and longs:
        plt.scatter(longs, 
                    lats, 
                    c=color.lower(), 
                    label=f"{color} Corridor", 
                    s=20, 
                    alpha=0.5,
                    zorder=order)

def visualize_polygon(polygon, order=2):
    try:
        polygon_path = polygon["path"] 
        polygon_label = polygon["label"] if "label" in polygon else None
        polygon_color = polygon["color"] if "color" in polygon else 'grey' 
        linestyle = polygon["linestyle"] if "linestyle" in polygon else 'solid'

        with open(polygon_path, 'r', encoding='utf-8') as f:
            polygon_json = json.load(f)
        coordinates = polygon_json["features"][0]["geometry"]["coordinates"][0]
        
        polygon_longitudes = [coord[0] for coord in coordinates]
        polygon_latitudes = [coord[1] for coord in coordinates]
        
        plt.plot(polygon_longitudes, 
                 polygon_latitudes, 
                 color=polygon_color, 
                 linewidth=1, 
                 label=polygon_label,
                 linestyle=linestyle,
                 zorder=order)
        
    except (KeyError, IndexError) as e:
        print(f"Error extracting boundary coordinates: {e}")

def visualize(csv_paths_by_color: dict | None = None, 
              main_polygons: list[dict] | None = None,
              background_polygons: list[dict] | None = None):
    
    plt.figure(figsize=(10, 8))

    if csv_paths_by_color:
        for color_name, file_path in csv_paths_by_color.items():
            visualize_points(color_name, file_path, order=3)

    if main_polygons:
        for polygon in main_polygons:
            visualize_polygon(polygon, order=2)

    #explicitly force dimensions
    xlim = plt.xlim()
    ylim = plt.ylim()

    xlim,ylim=pad_boundry(xlim,ylim,0.10)

    if background_polygons:
        for polygon in background_polygons:
            visualize_polygon(polygon, order=1)

    plt.xlim(xlim)
    plt.ylim(ylim)

    #added for better visualization
    # degree projection will have visual warp
    #adjusted for worcester,
    #hardcoded but if i *really* want this code to be flexible (for other places)
    #can be refactored (put in toolkit)
    aspect_ratio_adjustment_worcester = 1.35

    
    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.title("Transit Stop Coordinates")
    
    plt.gca().set_aspect(aspect_ratio_adjustment_worcester)
    
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend()
    plt.show()


points_dir = "data/processed/stops_organized_data"
dir_consol = "data/processed/stops_consolidated_data"

def visualize_tiered_stop_regions(tiered_geojson_path: str, stops_dict: dict, city_boundary_path: str = None):
    fig, ax = plt.subplots(figsize=(12, 12))

    bounds = {'min_x': float('inf'), 'max_x': float('-inf'),
              'min_y': float('inf'), 'max_y': float('-inf')}

    def update_bounds(x, y):
        if x < bounds['min_x']: bounds['min_x'] = x
        if x > bounds['max_x']: bounds['max_x'] = x
        if y < bounds['min_y']: bounds['min_y'] = y
        if y > bounds['max_y']: bounds['max_y'] = y

    with open(tiered_geojson_path, 'r', encoding='utf-8') as f:
        geojson_data = json.load(f)

    tiers = geojson_data.get("metadata", {}).get("distance_tiers_used", [])
    if not tiers:
        print("Warning: No 'distance_tiers_used' found in metadata. Using fallback max.")
        max_tier = 1000 
    else:
        max_tier = max(tiers)
    region_count = geojson_data.get("metadata", {}).get("total_regions")

    cmap = mcolors.LinearSegmentedColormap.from_list("red_to_white", ["red", "white"])

    for feature in geojson_data.get("features", []):
        geom = feature.get("geometry")
        props = feature.get("properties", {})
        if not geom: continue

        tier_str = props.get("tier", "0-0")
        stop_id = props.get("stop_id", "")

        if stop_id == "EXTERNAL" and tier_str == "BUFFER":
            lower_bound = max_tier
        else:
            try:
                lower_bound = float(tier_str.split("-")[0])
            except (ValueError, IndexError):
                lower_bound = 0

        color_val = cmap(lower_bound / max_tier)
        # -----------------------------------------------

        def add_polygon_patch(polygon_coords):
            vertices = []
            codes = []
            for ring in polygon_coords:
                for i, (lon, lat) in enumerate(ring):
                    vertices.append((lon, lat))
                    update_bounds(lon, lat) 
                    
                    if i == 0:
                        codes.append(mpath.Path.MOVETO)
                    elif i == len(ring) - 1:
                        codes.append(mpath.Path.CLOSEPOLY)
                    else:
                        codes.append(mpath.Path.LINETO)
            
            path = mpath.Path(vertices, codes)
            patch = mpatches.PathPatch(path, facecolor=color_val, edgecolor='black', linewidth=0.5, alpha=0.7)
            ax.add_patch(patch)

        geom_type = geom.get("type")
        if geom_type == "Polygon":
            add_polygon_patch(geom.get("coordinates", []))
        elif geom_type == "MultiPolygon":
            for poly_coords in geom.get("coordinates", []):
                add_polygon_patch(poly_coords)

    for color_name, path in stops_dict.items():
        lons, lats = [], []
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    lat = float(row['latitude'])
                    lon = float(row['longitude'])
                    lats.append(lat)
                    lons.append(lon)
                    update_bounds(lon, lat)
                except (ValueError, KeyError):
                    pass
        
        if lons and lats:
            ax.scatter(lons, lats, c=color_name.lower(), label=f"{color_name} Stops", 
                       zorder=5, s=20, edgecolors='black', linewidth=0.5)

    if bounds['min_x'] != float('inf'):
        pad_x = (bounds['max_x'] - bounds['min_x']) * 0.05
        pad_y = (bounds['max_y'] - bounds['min_y']) * 0.05
        
        ax.set_xlim(bounds['min_x'] - pad_x, bounds['max_x'] + pad_x)
        ax.set_ylim(bounds['min_y'] - pad_y, bounds['max_y'] + pad_y)

    if city_boundary_path:
        try:
            with open(city_boundary_path, 'r', encoding='utf-8') as f:
                boundary_data = json.load(f)
                
            for feature in boundary_data.get("features", []):
                geom = feature.get("geometry")
                if not geom: continue
                
                coords_list = []
                if geom["type"] == "Polygon":
                    coords_list = geom["coordinates"]
                elif geom["type"] == "MultiPolygon":
                    coords_list = [ring for poly in geom["coordinates"] for ring in poly]

                for ring in coords_list:
                    xs = [p[0] for p in ring]
                    ys = [p[1] for p in ring]
                    ax.plot(xs, ys, color='black', linestyle=':', linewidth=1.5, zorder=1)
                    
            ax.plot([], [], color='black', linestyle=':', label="City Boundary")
        except Exception as e:
            print(f"Failed to load/plot city boundary: {e}")

    ax.set_aspect(1.35) 
    ax.set_title(f"{region_count} Multi-Tier Catchment Areas", fontsize=14, pad=15)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(True, linestyle='--', alpha=0.3)
    ax.legend(loc='upper right')
    
    plt.tight_layout()
    plt.show()


points_to_visualize = {
    'Orange': f"{points_dir}/Orange_corridor_shared_stops.csv",
    'Blue': f"{points_dir}/Blue_corridor_shared_stops.csv",
    'Green': f"{points_dir}/Green_corridor_shared_stops.csv"
}

points_to_visualize_consolidated = {
    'Orange': f"{dir_consol}/Orange_corridor_shared_stops_consolidated.csv",
    'Blue': f"{dir_consol}/Blue_corridor_shared_stops_consolidated.csv",
    'Green': f"{dir_consol}/Green_corridor_shared_stops_consolidated.csv"
}

corridor_buffer_poly = {
    "path":"data/processed/area_around_stops/three_corridor_polygon_radius_400.geojson",
    "label":"400m radius around HF corridor stops",
    "color":"red"
}
corridor_buffer_poly_large = {
    "path":"data/processed/area_around_stops/three_corridor_polygon_radius_800.geojson",
    "label":"800m radius",
    "color":"red"
}

worcester_boundary = {
    "path":"data/raw/worcester_municipal_boundary.geojson",
    "label":"Worcester Municipal Boundary",
    "color":"red",
    "linestyle":"dashed"
}

# visualize(
#     points_to_visualize,
#     [corridor_buffer_poly],
#     [worcester_boundary])

# visualize(
#     points_to_visualize_consolidated,
#     [corridor_buffer_poly,corridor_buffer_poly_large],
#     [worcester_boundary])



# visualize_tiered_stop_regions(
#     #tiered_geojson_path="data/processed/area_around_stops/buffered_tiered_regions_around_stops.geojson",
#     tiered_geojson_path="data/processed/area_around_stops/buffered_tiered_regions_around_stops.geojson",
#     stops_dict=points_to_visualize_consolidated,
#     city_boundary_path="data/raw/worcester_municipal_boundary.geojson"
# )


