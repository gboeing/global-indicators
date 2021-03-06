"""

Define study region
~~~~~~~~~~~~~~~~~~~

::

    Script:  01_study_region_setup.py
    Purpose: Python set up study region boundaries and associated population resources

"""

import time
import os
import pandas as pd
import numpy as np
import geopandas as gpd
from geoalchemy2 import Geometry, WKTElement
from sqlalchemy import create_engine
from shapely.geometry import Polygon, MultiPolygon
import folium

from script_running_log import script_running_log

# Import custom variables for National Liveability indicator process
from _project_setup import *

def main():
    # simple timer for log file
    start = time.time()
    script = os.path.basename(sys.argv[0])
    task = 'create study region boundary'
    
    engine = create_engine(f"postgresql://{db_user}:{db_pwd}@{db_host}/{db}")
    
    population_linkage = {}
    gdf = {}
    area==analysis_scale
    urban_epsg =  int(df_datasets.loc['urban_region','epsg'])
    print("\tCreate study region boundary... ")
    if areas[area]['data'].startswith('GHS:'):
        # Global Human Settlements urban area is used to define this study region
        query = areas[area]['data'].replace('GHS:','')
        if "=" not in query:
            sys.exit('''
                A Global Human Settlements urban area was indicated for the study region, 
                however the query wasn't understood 
                (should be in format "GHS:field=value", 
                                 e.g. GHS:UC_NM_MN=Baltimore''')
        command = (
                ' ogr2ogr -overwrite -progress -f "PostgreSQL" ' 
                f' PG:"host={db_host} port={db_port} dbname={db}'
                f' user={db_user} password={db_pwd}" '
                f' {urban_region} '
                f' -lco geometry_name="geom" '
                ' -lco precision=NO '
                ' -nln full_urban_region '
                f' -where "{query}"'
                )
        print(command)
        sp.call(command, shell=True)
        sql = f'''
           DROP TABLE IF EXISTS urban_region;
           CREATE TABLE urban_region AS 
           SELECT ST_Transform(a.geom,{srid}) geom 
           FROM full_urban_region a;
           DROP TABLE full_urban_region;
           CREATE INDEX urban_region_gix ON urban_region USING GIST (geom);
           '''
        engine.execute(sql)
        sql = f'''
                 DROP TABLE IF EXISTS {study_region};
                 CREATE TABLE IF NOT EXISTS {study_region} AS 
                    SELECT '{full_locale}'::text AS "Study region", 
                           '{db}'::text AS "db",
                           ST_Area(geom)/10^6 AS area_sqkm,
                           ST_Transform(geom,4326) AS geom_4326,
                           geom
                    FROM urban_region;
                 CREATE INDEX {study_region}_gix ON {study_region} USING GIST (geom);
                 '''
        engine.execute(sql)
    else:
        # use alternative boundary for study region
        if areas[area]['data'].endswith('zip'):
            # Open zipped file as geodataframe
            gdf[area] = gpd.read_file('zip://../{}'.format(areas[area]['data']))
        if '.gpkg:' in areas[area]['data']:
            gpkg = areas[area]['data'].split(':')
            gdf[area] = gpd.read_file('../{}'.format(gpkg[0]), layer=gpkg[1])
        else:
            try:
                # Open spatial file as geodataframe
                gdf[area] = gpd.read_file('../{}'.format(areas[area]['data'])) 
            except:
                sys.exit("Error reading in boundary data (check format): "+sys.exc_info()[0])
        
        gdf[area] = gdf[area][['geometry']]
        gdf[area]["Study region"] = full_locale    
        gdf[area] = gdf[area].set_index("Study region")
        gdf[area]['db'] = db
        gdf[area].to_crs(epsg=srid, inplace=True)
        gdf[area]['area_sqkm'] = gdf[area]['geometry'].area/10**6
        # Create WKT geometry (postgis won't read shapely geometry)
        gdf[area]["geometry"] = [MultiPolygon([feature]) if type(feature) == Polygon else feature for feature in gdf[area]["geometry"]]
        gdf[area]['geom'] = gdf[area]['geometry'].apply(lambda x: WKTElement(x.wkt, srid=srid))
        # Drop original shapely geometry
        gdf[area].drop('geometry', 1, inplace=True)
        # Ensure all geometries are multipolygons (specifically - can't be mixed type; complicates things)
        # Copy to project Postgis database
        gdf[area].to_sql(study_region, engine, if_exists='replace', index=True, dtype={'geom': Geometry('MULTIPOLYGON', srid=srid)})
        print('\t{} {}'.format(len(gdf[area]),areas[area]['name']))
        sql = f'''
        ALTER TABLE {study_region} ADD COLUMN geom_4326 geometry;
        UPDATE {study_region} SET geom_4326 =  ST_Transform(geom,4326);
        '''
        engine.execute(sql)
    
    print(f"\tCreate {study_buffer} m buffered study region... ")
    study_buffer_km = study_buffer/1000
    buffered_study_region_extent = f'{study_buffer_km} km'
    sql = f'''
    DROP TABLE IF EXISTS {buffered_study_region}; 
    CREATE TABLE {buffered_study_region} AS 
          SELECT "Study region",
                 db,
                 '{buffered_study_region_extent}'::text AS "Study region buffer", 
                 ST_Transform(ST_Buffer(geom,{study_buffer}),4326) AS geom_4326,
                 ST_Buffer(geom,{study_buffer}) AS geom 
            FROM  {study_region} ;
    CREATE INDEX  {buffered_study_region}_gix ON  {buffered_study_region} USING GIST (geom);
    '''
    engine.execute(sql)

    if areas[area]['data'].startswith('GHS'):
        sql = f'''
            DROP TABLE IF EXISTS urban_study_region;
            CREATE TABLE urban_study_region AS 
            SELECT "Study region",
                   geom 
            FROM {study_region};
            CREATE INDEX urban_study_region_gix ON urban_study_region USING GIST (geom);
            '''
        engine.execute(sql)        
    else:
        if not_urban_intersection:
            # e.g. Vic is not represented in the GHS data, so intersection is not used
            for table in ['urban_region','urban_study_region']:
                sql = f'''
                DROP TABLE IF EXISTS {table};
                CREATE TABLE {table} AS
                SELECT * FROM {study_region};
                CREATE INDEX {table}_gix ON {table} USING GIST (geom);
                '''
                engine.execute(sql)
        else:
            if urban_region not in ['','nan']:
                if not engine.has_table('urban_region'):
                    clipping_boundary = gpd.GeoDataFrame.from_postgis('''SELECT geom FROM {table}'''.format(table = buffered_study_region), engine, geom_col='geom' )   
                    command = (
                            ' ogr2ogr -overwrite -progress -f "PostgreSQL" ' 
                            f' PG:"host={db_host} port={db_port} dbname={db}'
                            f' user={db_user} password={db_pwd}" '
                            f' {urban_region} '
                            f' -lco geometry_name="geom" '
                            ' -lco precision=NO '
                            ' -nln full_urban_region '
                            )
                    print(command)
                    sp.call(command, shell=True)
                    sql = f'''
                       DROP TABLE IF EXISTS urban_region;
                       CREATE TABLE urban_region AS 
                       SELECT ST_Transform(a.geom,{srid}) geom 
                       FROM full_urban_region a,
                       {buffered_study_region} b 
                       WHERE ST_Intersects(a.geom,ST_Transform(b.geom,{urban_epsg}));
                       DROP TABLE full_urban_region;
                       CREATE INDEX urban_region_gix ON urban_region USING GIST (geom);
                       '''
                    engine.execute(sql)
            if not engine.has_table('urban_study_region'):
                sql = f'''
                   CREATE TABLE urban_study_region AS 
                   SELECT "Study region",
                          ST_Union(ST_Intersection(a.geom,b.geom)) geom 
                   FROM {study_region} a,
                   urban_region b
                   GROUP BY "Study region";
                   CREATE INDEX urban_study_region_gix ON urban_study_region USING GIST (geom);
                '''
                engine.execute(sql)
 
    print('')
    # output to completion log					
    script_running_log(script, task, start, locale)
    engine.dispose()
    
if __name__ == '__main__':
    main()