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
from src.config import debug_mode
from shapely import voronoi_polygons
from shapely.geometry import Point, MultiPoint, mapping
from shapely.ops import transform, unary_union
from src.toolkits.geometric_toolset import project_from_deg_to_meters, project_from_meters_to_degrees

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
    
# radius_meters = 800
# src_dir = "data/processed/stops_organized_data"
# dest_dir = "data/processed/area_around_stops"
# generate_geojson_polygon(
#     f"{src_dir}/all_stops_on_HF_corridors.csv",
#     f"{dest_dir}/three_corridor_polygon_radius_{radius_meters}.geojson",
#     radius_meters=radius_meters)

def generate_many_regions(stops_paths:list[str],distance_tiers:list[int],output_path:str):

    distance_tiers = sorted(distance_tiers, reverse=True) #descending

    stop_ids = []
    stop_lats = []
    stop_longs = []

    resulting_polygons = {}
    #maybe not needed
    dist_tier_ranges = []
    for i in range(len(distance_tiers)-1):
        dist_range_tuple = (distance_tiers[i],distance_tiers[i+1])
        dist_tier_ranges.append(dist_range_tuple) #end maybe not needed

    for path in stops_paths:
        with open(path, mode='r') as stops_file:
            reader = csv.DictReader(stops_file)
            for row in reader:
                stop_id = row["stop_id"]
                stop_ids.append(stop_id)
                stop_lats.append(float(row["latitude"]))
                stop_longs.append(float(row["longitude"]))
                resulting_polygons[stop_id]={dist_range: {} for dist_range in dist_tier_ranges} #maybe not needed, just do resulting_polygons[stop_id]={}

    if debug_mode: print("stops data recorded")

    points_degrees = MultiPoint([Point(long,lat) for  long, lat in zip(stop_longs, stop_lats)])
    points_meters = transform(project_from_deg_to_meters, points_degrees)

    if debug_mode: print("transformed from degrees")

    stop_data_intermediate = [{
        'stop_id':stop_id,
        'coords_m':coords} for stop_id, coords in zip(stop_ids, points_meters.geoms)]

    greatest_distance = max(distance_tiers)
    greatest_distance_buffers = [coords.buffer(greatest_distance) for coords in points_meters.geoms]
    greatest_corridor_buffer = unary_union(greatest_distance_buffers)

    #this will mess up order, so need to reconfigure to align w stop ids
    voronoi_poly_raw = voronoi_polygons(points_meters) #voronois for biggest dist tier, inclusive of smaller tiers

    if debug_mode: print("raw voronoi polygons generated")

    for stop_data in stop_data_intermediate: 
        for voronoi_raw in voronoi_poly_raw.geoms:
            if voronoi_raw.distance(stop_data['coords_m']) < 1e-6:
                stop_data['voronoi_max_inc'] = voronoi_raw.intersection(greatest_corridor_buffer)
                break

    if debug_mode: print("ordered voronoi polygons")
    
    for stop_data in stop_data_intermediate:
        current_voronoi = stop_data['voronoi_max_inc']
        coords_m = stop_data['coords_m']
        stop_id = stop_data['stop_id']

        if debug_mode: print(f"assessing stop {stop_id}")

        for tier_range in dist_tier_ranges:

            (outer_ring_d, inner_ring_d)=tier_range
            voronoi_inner = coords_m.buffer(inner_ring_d).intersection(current_voronoi)
            final_voronoi_meters = current_voronoi.difference(voronoi_inner)

            if not final_voronoi_meters.is_empty:
                shrunk_voronoi_meters = final_voronoi_meters.buffer(-0.1)#buffer so polygons dont overlap on tomtom
                if not shrunk_voronoi_meters.is_empty:
                    final_voronoi_degrees = transform(project_from_meters_to_degrees, shrunk_voronoi_meters)
                    resulting_polygons[stop_id][tier_range] = mapping(final_voronoi_degrees)
            current_voronoi = voronoi_inner

        if not current_voronoi.is_empty:
            shrunk_core_meters = current_voronoi.buffer(-0.1)#buffer for tomtom
            if not shrunk_core_meters.is_empty:
                final_voronoi_degrees = transform(project_from_meters_to_degrees, shrunk_core_meters)
                resulting_polygons[stop_id][(distance_tiers[-1],0)] = mapping(final_voronoi_degrees)
    
    flat_features = []

    if debug_mode: print("flattening data")
    for stop_id, tiers in resulting_polygons.items():
        for tier_range, geometry in tiers.items():

            outer_d, inner_d = tier_range
            tier_label = f"{inner_d}-{outer_d}m"

            if geometry:
                feature = {
                    "type": "Feature",
                    "properties": {
                        "stop_id": stop_id,
                        "tier": tier_label,
                        "name": f"{stop_id}_{tier_label}"
                    },
                    "geometry": geometry
                }
                flat_features.append(feature)

    #generate a buffer outside of greatest buffer
    #needed for tomtom data
    outer_buffer_inc = greatest_corridor_buffer.buffer(200)
    outer_buffer = outer_buffer_inc.difference(greatest_corridor_buffer)
    outer_buffer = outer_buffer.buffer(-0.1)
    outer_buffer_meters = transform(project_from_meters_to_degrees,outer_buffer)

    outer_buffer_feature = {
                    "type": "Feature",
                    "properties": {
                        "stop_id": "EXTERNAL",
                        "tier": "BUFFER",
                        "name": "TRANSITION_ZONE"
                    },
                    "geometry": mapping(outer_buffer_meters)
                    }
    flat_features.append(outer_buffer_feature)


    feature_collection = {
        "type": "FeatureCollection",
        "metadata": {
            "distance_tiers_used": distance_tiers,
            "total_regions":len(flat_features)
        },
        "features": flat_features
    }
    if debug_mode: print("writing data to json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(feature_collection, f, indent=2)

    if debug_mode: print(f"Successfully generated {len(flat_features)} multi-tier catchments and saved to {output_path}")

# generate_many_regions(
#                      ["data/processed/stops_consolidated_data/all_stops_on_HF_corridors_consolidated.csv"],
#                      [800,600,400,200,100],
#                      "data/processed/area_around_stops/buffered_tiered_regions_around_stops.geojson"
# )

generate_many_regions(
                    ["data/processed/stops_consolidated_data/all_stops_on_HF_corridors_consolidated.csv"],
                    [400],
                    "data/processed/area_around_stops/buffered_regions_around_stops_no_tiers.geojson"
                    )

