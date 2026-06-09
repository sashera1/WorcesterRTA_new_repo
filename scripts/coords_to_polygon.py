"""
DESC:
takes coords from csv (format: stop_id, lat, lon) and creates a polygon 
encompassing the union of (an approximation of) circles of a certain radius around each stop
output should be a geojson such that can be useds for tomtom

NOTE:
1) input is lat,long but geojson needs to be long, lat
2) these are as degrees: must be converted to non-degree system for distance calc
and then back
"""
import csv
import json
from shapely.geometry import Point, MultiPoint, mapping
from shapely.ops import transform
from src.toolkits.geometric_toolset import project_from_deg_to_meters, project_from_meters_to_degrees

#refactor schema:
"""
load_coords_from_csv(filepath) -> list
create_transformers(center_lat, center_lon) -> tuple
create_buffered_polygon(points, radius_meters) -> Polygon
save_to_geojson(geometry, filepath)
OR
Migrate to GeoPandas (Industry Standard)
"""

def generate_geojson_polygon(input_file:str,output_polygon_file:str, radius_meters: float):
    
    input_data = []
    with open(input_file, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Check for valid lat/lon to avoid breaking on malformed rows
            if row.get('latitude') and row.get('longitude'):
                input_data.append(
                    [float(row["latitude"]),
                     float(row["longitude"])]
                )    

    points_degrees = MultiPoint([Point(item[1], item[0]) for item in input_data])

    points_meters = transform(project_from_deg_to_meters, points_degrees)

    polygon_meters = points_meters.buffer(radius_meters, quad_segs=16)

    polygon_degrees = transform(project_from_meters_to_degrees, polygon_meters)
    
    #TODO delete after verifying refactor works
    # circles = []
    # for item in input_data:
    #     # note lat, long are swapped! geojson format does it different from gtfs format
    #     p_degrees = Point(item[1], item[0])
        
    #     #transform to meters, draw the circle, and transform back to degrees
    #     p_meters = transform(project_from_deg_to_meters, p_degrees)
    #     circle_meters = p_meters.buffer(radius_meters, quad_segs=16)
    #     circle_degrees = transform(project_from_meters_to_degrees, circle_meters)
        
    #     circles.append(circle_degrees)

    #     unioned_geometry = unary_union(circles)

    geojson_dict = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                # mapping converts a shapely object into geojson
                "geometry": mapping(polygon_degrees) 
            }
        ]
    }

    with open(output_polygon_file, mode='w', encoding='utf-8') as f:
        json.dump(geojson_dict, f, indent=2)
    
radius_meters = 400
src_dir = "data/processed/stops_organized_data"
dest_dir = "data/processed/area_around_stops"
generate_geojson_polygon(
    f"{src_dir}/all_stops_on_HF_corridors.csv",
    f"{dest_dir}/three_corridor_polygon_radius_{radius_meters}.geojson",
    radius_meters=radius_meters)