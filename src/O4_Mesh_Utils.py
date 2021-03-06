import time
import sys
import os
import subprocess
import numpy
from math import sqrt
#from PIL import Image
import O4_UI_Utils as UI
import O4_File_Names as FNAMES
import O4_Geo_Utils as GEO
import O4_Vector_Utils as VECT
import O4_OSM_Utils as OSM
import O4_Config_Utils as CFG

if 'dar' in sys.platform:
    Triangle4XP_cmd = os.path.join(FNAMES.Utils_dir,"Triangle4XP_v130.app ")
    triangle_cmd    = os.path.join(FNAMES.Utils_dir,"triangle.app ")
elif 'win' in sys.platform: 
    Triangle4XP_cmd = os.path.join(FNAMES.Utils_dir,"Triangle4XP_v130.exe ")
    triangle_cmd    = os.path.join(FNAMES.Utils_dir,"triangle.exe ")
else:
    Triangle4XP_cmd = os.path.join(FNAMES.Utils_dir,"Triangle4XP_v130 ")
    triangle_cmd    = os.path.join(FNAMES.Utils_dir,"triangle ")

##############################################################################
def is_in_region(lat,lon,latmin,latmax,lonmin,lonmax):
    return lat>=latmin and lat<=latmax and lon>=lonmin and lon<=lonmax
##############################################################################

##############################################################################
def build_curv_tol_weight_map(tile,weight_array):
    if tile.apt_curv_tol!=tile.curvature_tol:
        UI.vprint(1,"-> Modifying curv_tol weight map according to runway locations.")
        airport_layer=OSM.OSM_layer()
        queries=[('rel["aeroway"="runway"]','rel["aeroway"="taxiway"]','rel["aeroway"="apron"]',
          'way["aeroway"="runway"]','way["aeroway"="taxiway"]','way["aeroway"="apron"]')]
        tags_of_interest=["all"]
        if not OSM.OSM_queries_to_OSM_layer(queries,airport_layer,tile.lat,tile.lon,tags_of_interest,cached_suffix='airports'): 
            return 0
        runway_network=OSM.OSM_to_MultiLineString(airport_layer,tile.lat,tile.lon)
        runway_area=VECT.improved_buffer(runway_network,0.0003,0.0001,0.00001)
        if not runway_area: return 0
        runway_area=VECT.ensure_MultiPolygon(runway_area)
        for polygon in runway_area.geoms if ('Multi' in runway_area.geom_type or 'Collection' in runway_area.geom_type) else [runway_area]:
            (xmin,ymin,xmax,ymax)=polygon.bounds
            x_shift=1000*tile.apt_curv_ext*GEO.m_to_lon(tile.lat) 
            y_shift=1000*tile.apt_curv_ext*GEO.m_to_lat
            colmin=round((xmin-x_shift)*1000)
            colmax=round((xmax+x_shift)*1000)
            rowmax=round(((1-ymin)+y_shift)*1000)
            rowmin=round(((1-ymax)-y_shift)*1000)
            weight_array[rowmin:rowmax+1,colmin:colmax+1]=tile.curvature_tol/tile.apt_curv_tol if tile.apt_curv_tol>0 else 1 
        del(airport_layer)
        del(runway_network) 
        del(runway_area)
    if tile.coast_curv_tol!=tile.curvature_tol:
        UI.vprint(1,"-> Modifying curv_tol weight map according to coastline location.")
        sea_layer=OSM.OSM_layer()
        queries=['way["natural"="coastline"]']    
        tags_of_interest=[]
        if not OSM.OSM_queries_to_OSM_layer(queries,sea_layer,tile.lat,tile.lon,tags_of_interest,cached_suffix='coastline'):
            return 0
        for nodeid in sea_layer.dicosmn:
            (lonp,latp)=[float(x) for x in sea_layer.dicosmn[nodeid]]
            x_shift=1000*tile.coast_curv_ext*GEO.m_to_lon(tile.lat)
            y_shift=tile.coast_curv_ext/(111.12)
            colmin=round((lonp-tile.lon-x_shift)*1000)
            colmax=round((lonp-tile.lon+x_shift)*1000)
            rowmax=round((tile.lat+1-latp+y_shift)*1000)
            rowmin=round((tile.lat+1-latp-y_shift)*1000)
            weight_array[rowmin:rowmax+1,colmin:colmax+1]=tile.curvature_tol/tile.coast_curv_tol if tile.coast_curv_tol>0 else 1 
        del(sea_layer)
    # It could be of interest to write the weight file as a png for user editing    
    #Image.fromarray((weight_array!=1).astype(numpy.uint8)*255).save('weight.png')
    return
##############################################################################

##############################################################################
def post_process_nodes_altitudes(tile):
    dico_attributes=VECT.Vector_Map.dico_attributes 
    f_node = open(FNAMES.output_node_file(tile),'r')
    init_line_f_node=f_node.readline()
    nbr_pt=int(init_line_f_node.split()[0])
    vertices=numpy.zeros(6*nbr_pt)   
    UI.vprint(1,"-> Loading of the mesh computed by Triangle4XP.")
    for i in range(0,nbr_pt):
        vertices[6*i:6*i+6]=[float(x) for x in f_node.readline().split()[1:7]]
    end_line_f_node=f_node.readline()
    f_node.close()
    UI.vprint(1,"-> Smoothing elevation file for airport levelling.")
    tile.dem.smoothen(tile.apt_smoothing_pix)
    UI.vprint(1,"-> Post processing of altitudes according to vector data")
    f_ele  = open(FNAMES.output_ele_file(tile),'r')
    nbr_tri= int(f_ele.readline().split()[0])
    water_tris=set()
    sea_tris=set()
    smoothed_alt_tris=set()
    interp_alt_tris=set()
    for i in range(nbr_tri):
        line = f_ele.readline()
        (v1,v2,v3,attr)=[int(x)-1 for x in line.split()[1:5]]
        attr+=1
        if attr & dico_attributes['INTERP_ALT']: 
            interp_alt_tris.add((v1,v2,v3))
        elif attr & dico_attributes['SMOOTHED_ALT'] and not tile.iterate: 
            smoothed_alt_tris.add((v1,v2,v3))
        elif attr & dico_attributes['SEA']:
            sea_tris.add((v1,v2,v3))
        elif attr & dico_attributes['WATER']:
            water_tris.add((v1,v2,v3))
    if tile.water_smoothing:
        UI.vprint(1,"   Smoothing inland water.")
        for j in range(tile.water_smoothing):   
            for (v1,v2,v3) in water_tris:
                    zmean=(vertices[6*v1+2]+vertices[6*v2+2]+vertices[6*v3+2])/3
                    vertices[6*v1+2]=zmean
                    vertices[6*v2+2]=zmean
                    vertices[6*v3+2]=zmean
    UI.vprint(1,"   Smoothing of sea water.")
    for (v1,v2,v3) in sea_tris:
            if tile.sea_smoothing_mode==0:
                vertices[6*v1+2]=0
                vertices[6*v2+2]=0
                vertices[6*v3+2]=0
            elif tile.sea_smoothing_mode==1:
                zmean=(vertices[6*v1+2]+vertices[6*v2+2]+vertices[6*v3+2])/3
                vertices[6*v1+2]=zmean
                vertices[6*v2+2]=zmean
                vertices[6*v3+2]=zmean
            else:
                vertices[6*v1+2]=max(vertices[6*v1+2],0)
                vertices[6*v2+2]=max(vertices[6*v2+2],0)
                vertices[6*v3+2]=max(vertices[6*v3+2],0)
    UI.vprint(1,"   Smoothing of airports.")
    for (v1,v2,v3) in smoothed_alt_tris:
            vertices[6*v1+2]=tile.dem.alt_vec(numpy.array([[vertices[6*v1],vertices[6*v1+1]]]))
            vertices[6*v2+2]=tile.dem.alt_vec(numpy.array([[vertices[6*v2],vertices[6*v2+1]]]))
            vertices[6*v3+2]=tile.dem.alt_vec(numpy.array([[vertices[6*v3],vertices[6*v3+1]]]))
    UI.vprint(1,"   Treatment of roads and patches.")
    for (v1,v2,v3) in interp_alt_tris:
            vertices[6*v1+2]=vertices[6*v1+5]
            vertices[6*v2+2]=vertices[6*v2+5]
            vertices[6*v3+2]=vertices[6*v3+5]
    UI.vprint(1,"-> Writing output nodes file.")        
    f_node = open(FNAMES.output_node_file(tile),'w')
    f_node.write(init_line_f_node)
    for i in range(0,nbr_pt):
        f_node.write(str(i+1)+" "+' '.join(('{:.15f}'.format(x) for x in vertices[6*i:6*i+6]))+"\n")
    f_node.write(end_line_f_node)
    f_node.close()
    return vertices
##############################################################################

##############################################################################
def write_mesh_file(tile,vertices):
    UI.vprint(1,"-> Writing final mesh to the file "+FNAMES.mesh_file(tile.build_dir,tile.lat,tile.lon))
    f_ele  = open(FNAMES.output_ele_file(tile),'r')
    nbr_vert=len(vertices)//6
    nbr_tri=int(f_ele.readline().split()[0])
    f=open(FNAMES.mesh_file(tile.build_dir,tile.lat,tile.lon),"w")
    f.write("MeshVersionFormatted 1\n")
    f.write("Dimension 3\n\n")
    f.write("Vertices\n")
    f.write(str(nbr_vert)+"\n")
    for i in range(0,nbr_vert):
        f.write('{:.9f}'.format(vertices[6*i]+tile.lon)+" "+\
                '{:.9f}'.format(vertices[6*i+1]+tile.lat)+" "+\
                '{:.9f}'.format(vertices[6*i+2]/100000)+" 0\n") 
    f.write("\n")
    f.write("Normals\n")
    f.write(str(nbr_vert)+"\n")
    for i in range(0,nbr_vert):
        f.write('{:.9f}'.format(vertices[6*i+3])+" "+\
                '{:.9f}'.format(vertices[6*i+4])+"\n")
    f.write("\n")
    f.write("Triangles\n")
    f.write(str(nbr_tri)+"\n")
    for i in range(0,nbr_tri):
       f.write(' '.join(f_ele.readline().split()[1:])+"\n")
    f_ele.close()
    f.close()
    return
##############################################################################

##############################################################################
# Build a textured .obj wavefront over the extent of an orthogrid cell
##############################################################################
def extract_mesh_to_obj(mesh_file,til_x_left,til_y_top,zoomlevel,provider_code): 
    timer=time.time()
    (latmax,lonmin)=GEO.gtile_to_wgs84(til_x_left,til_y_top,zoomlevel)
    (latmin,lonmax)=GEO.gtile_to_wgs84(til_x_left+16,til_y_top+16,zoomlevel)
    obj_file_name=FNAMES.obj_file(til_x_left,til_y_top,zoomlevel,provider_code)
    mtl_file_name=FNAMES.mtl_file(til_x_left,til_y_top,zoomlevel,provider_code)
    f_mesh=open(mesh_file,"r")
    for i in range(4):
        f_mesh.readline()
    nbr_pt_in=int(f_mesh.readline())
    pt_in=numpy.zeros(5*nbr_pt_in,'float')
    for i in range(nbr_pt_in):
        pt_in[5*i:5*i+3]=[float(x) for x in f_mesh.readline().split()[:3]]
    for i in range(3):
        f_mesh.readline()
    for i in range(nbr_pt_in):
        pt_in[5*i+3:5*i+5]=[float(x) for x in f_mesh.readline().split()[:2]]
    for i in range(0,2): # skip 2 lines
        f_mesh.readline()
    nbr_tri_in=int(f_mesh.readline()) # read nbr of tris
    textured_nodes={}
    textured_nodes_inv={}
    nodes_st_coord={}
    len_textured_nodes=0
    dico_new_tri={}
    len_dico_new_tri=0
    for i in range(0,nbr_tri_in):
        (n1,n2,n3)=[int(x)-1 for x in f_mesh.readline().split()[:3]]
        (lon1,lat1,z1,u1,v1)=pt_in[5*n1:5*n1+5]
        (lon2,lat2,z2,u2,v2)=pt_in[5*n2:5*n2+5]
        (lon3,lat3,z3,u3,v3)=pt_in[5*n3:5*n3+5]
        if is_in_region((lat1+lat2+lat3)/3.0,(lon1+lon2+lon3)/3.0,latmin,latmax,lonmin,lonmax):
            if n1 not in textured_nodes_inv:
                len_textured_nodes+=1 
                textured_nodes_inv[n1]=len_textured_nodes
                textured_nodes[len_textured_nodes]=n1
                nodes_st_coord[len_textured_nodes]=GEO.st_coord(lat1,lon1,til_x_left,til_y_top,zoomlevel,provider_code)
            n1new=textured_nodes_inv[n1]
            if n2 not in textured_nodes_inv:
                len_textured_nodes+=1 
                textured_nodes_inv[n2]=len_textured_nodes
                textured_nodes[len_textured_nodes]=n2
                nodes_st_coord[len_textured_nodes]=GEO.st_coord(lat2,lon2,til_x_left,til_y_top,zoomlevel,provider_code)
            n2new=textured_nodes_inv[n2]
            if n3 not in textured_nodes_inv:
                len_textured_nodes+=1 
                textured_nodes_inv[n3]=len_textured_nodes
                textured_nodes[len_textured_nodes]=n3
                nodes_st_coord[len_textured_nodes]=GEO.st_coord(lat3,lon3,til_x_left,til_y_top,zoomlevel,provider_code)
            n3new=textured_nodes_inv[n3]
            dico_new_tri[len_dico_new_tri]=(n1new,n2new,n3new)
            len_dico_new_tri+=1
    nbr_vert=len_textured_nodes
    nbr_tri=len_dico_new_tri
    # first the obj file
    f=open(obj_file_name,"w")
    for i in range(1,nbr_vert+1):
        j=textured_nodes[i]
        f.write("v "+'{:.9f}'.format(pt_in[5*j]-lonmin)+" "+\
                '{:.9f}'.format(pt_in[5*j+1]-latmin)+" "+\
                '{:.9f}'.format(pt_in[5*j+2])+"\n") 
    f.write("\n")
    for i in range(1,nbr_vert+1):
        j=textured_nodes[i]
        f.write("vn "+'{:.9f}'.format(pt_in[5*j+3])+" "+\
                '{:.9f}'.format(pt_in[5*j+4])+" "+'{:.9f}'.format(sqrt(max(1-pt_in[5*j+3]**2-pt_in[5*j+4]**2),0))+"\n")
    f.write("\n")
    for i in range(1,nbr_vert+1):
        j=textured_nodes[i]
        f.write("vt "+'{:.9f}'.format(nodes_st_coord[i][0])+" "+\
                '{:.9f}'.format(nodes_st_coord[i][1])+"\n")
    f.write("\n")
    f.write("usemtl orthophoto\n\n")
    for i in range(0,nbr_tri):
        (one,two,three)=dico_new_tri[i]
        f.write("f "+str(one)+"/"+str(one)+"/"+str(one)+" "+str(two)+"/"+str(two)+"/"+str(two)+" "+str(three)+"/"+str(three)+"/"+str(three)+"\n")
    f_mesh.close()
    f.close()
    # then the mtl file
    f=open(mtl_file_name,'w')
    f.write("newmtl orthophoto\nmap_Kd "+FNAMES.geotiff_file_name_from_attributes(til_x_left,til_y_top,zoomlevel,provider_code)+"\n")
    f.close()
    UI.timings_and_bottom_line(timer)
    return
##############################################################################


##############################################################################
def build_mesh(tile):
    UI.red_flag=False    
    UI.logprint("Step 2 for tile lat=",tile.lat,", lon=",tile.lon,": starting.")
    UI.vprint(0,"\nStep 2 : Building mesh tile "+FNAMES.short_latlon(tile.lat,tile.lon)+" : \n--------\n")
    UI.progress_bar(1,0)
    timer=time.time()
    tri_verbosity='Q' if UI.verbosity<=1 else 'V'
    tile_log=open(os.path.join(FNAMES.Tile_dir,'zOrtho4XP_' + FNAMES.short_latlon(tile.lat,tile.lon),FNAMES.short_latlon(tile.lat,tile.lon) + ".log"), 'w+')
    if tile.iterate==0:
        Tri_option = '-pAuYB'+tri_verbosity
    else:
        Tri_option = '-pruYB'+tri_verbosity
    poly_file    = FNAMES.input_poly_file(tile)
    alt_file     = FNAMES.alt_file(tile)
    weight_file  = FNAMES.weight_file(tile)
    if not os.path.isfile(poly_file):
        UI.exit_message_and_bottom_line("\nERROR: Could not find ",poly_file)
        return 0
    
    tile.ensure_elevation_data()
    if UI.red_flag: UI.exit_message_and_bottom_line(); return 0
    tile.dem.write_to_file(alt_file)
    
    weight_array=numpy.ones((1000,1000),dtype=numpy.float32)
    build_curv_tol_weight_map(tile,weight_array)
    weight_array.tofile(weight_file)
    
    del(weight_array)
    curv_tol = tile.curvature_tol
    curv_tol_scaling=tile.dem.nxdem/(1000*(tile.dem.x1-tile.dem.x0))
    hmin_effective=max(tile.hmin,(tile.dem.y1-tile.dem.y0)*GEO.lat_to_m/tile.dem.nydem/2)
    while True:
        mesh_cmd=[Triangle4XP_cmd.strip(),
                  Tri_option.strip(),
                  '{:.9g}'.format(GEO.lon_to_m(tile.lat)),
                  '{:.9g}'.format(GEO.lat_to_m),
                  '{:n}'.format(tile.dem.nxdem),
                  '{:n}'.format(tile.dem.nydem),
                  '{:.9g}'.format(tile.dem.x0),
                  '{:.9g}'.format(tile.dem.y0),
                  '{:.9g}'.format(tile.dem.x1),
                  '{:.9g}'.format(tile.dem.y1),
                  '{:.9g}'.format(tile.dem.nodata),
                  '{:.9g}'.format(curv_tol*curv_tol_scaling),
                  '{:.9g}'.format(tile.min_angle),str(hmin_effective),alt_file,weight_file,poly_file]

        UI.vprint(1,"-> Start of the mesh algorithm Triangle4XP.")
        UI.vprint(2,'  Mesh command:',' '.join(mesh_cmd))
        fingers_crossed=subprocess.Popen(mesh_cmd,stdout=subprocess.PIPE,bufsize=0)
        while True:
            line = fingers_crossed.stdout.readline()
            if not line: 
                break
            else:
                print(line.decode("utf-8")[:-1])
                tile_log.write(line.decode("utf-8"))
        fingers_crossed.poll()
        if fingers_crossed.returncode:
            UI.exit_message_and_bottom_line("\nERROR: Triangle4XP crashed !\n\n"+\
                                            "If the reason is not due to the limited amount of RAM please\n"+\
                                            "file a bug including the .node and .poly files for that you\n"+\
                                            "will find in "+str(tile.build_dir)+".\n")
            tile_log.write(line.decode("utf-8"))
            tile_log.close()
            break
        else:
            f_ele=open(FNAMES.output_ele_file(tile),'r')
            nbr_tri=int(f_ele.readline().split()[0])
            f_ele.close()

        if nbr_tri >= tile.min_tri and nbr_tri <= tile.max_tri:
            UI.vprint(1, "Triangles within min/max range, continuing.\n")
            break
        elif nbr_tri <= tile.min_tri and curv_tol <= 0.2:
            UI.vprint(1, "Triangles less than minimum, but curv_tol at lower threshhold.")
            curv_tol = 0.2
            break
        elif curv_tol >= 20.0:
            UI.vprint(1, "curv_tol too high, error.")
            curv_tol = 20.0
            break
        elif nbr_tri <= tile.min_tri and curv_tol >=0.2:
            if curv_tol < 2.0:
                curv_tol -= 0.1
            else:
                curv_tol = round((curv_tol + 0.2) / 2, 2)
            if curv_tol < 0.2:
                    curv_tol = 0.2
            UI.vprint(1, "Triangles less than minimum, reducing curv_tol to " + str(curv_tol))
        elif nbr_tri >= tile.max_tri:
            if curv_tol < 3.0:
                curv_tol += 0.1
            else:
                curv_tol += 0.5
            UI.vprint(1, "Triangles above maximum, increasing curv_tol to " + str(curv_tol))
        else:
            UI.vprint(1, "curv_tol adjusment error, continuing.")
            break
    if tile.curvature_tol != curv_tol:
        UI.vprint(1, "Updating stored curv_tol in config file for tile to " + str(curv_tol))
        tile.curvature_tol = curv_tol
        tile.write_to_config()
    tile_log.close()
    if UI.red_flag: UI.exit_message_and_bottom_line(); return 0
    
    vertices=post_process_nodes_altitudes(tile)
    tile.dem=None  # post_processing has introduced smoothing, we trash the dem data

    if UI.red_flag: UI.exit_message_and_bottom_line(); return 0

    write_mesh_file(tile,vertices)
    #
    UI.timings_and_bottom_line(timer)
    UI.logprint("Step 2 for tile lat=",tile.lat,", lon=",tile.lon,": normal exit.")
    return 1
##############################################################################

##############################################################################
def triangulate(name,path_to_Ortho4XP_dir):
    Tri_option = ' -pAYPQ '
    mesh_cmd=[os.path.join(path_to_Ortho4XP_dir,triangle_cmd).strip(),Tri_option.strip(),name+'.poly']
    fingers_crossed=subprocess.Popen(mesh_cmd,stdout=subprocess.PIPE,bufsize=0)
    while True:
        line = fingers_crossed.stdout.readline()
        if not line: 
            break
        else:
            print(line.decode("utf-8")[:-1])
    fingers_crossed.poll()  
    if fingers_crossed.returncode:
        print("\nERROR: triangle crashed, check osm mask data.\n")
        return 0
    return 1
##############################################################################   
