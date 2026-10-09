import numpy as np
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import box
from deteccion_terreno import detectar

def test_drenaje_sintetico():
    h=w=90
    yy,xx=np.indices((h,w))
    # Valle pronunciado, caída hacia el sur y zona de piedemonte
    z=(1300-yy*2.4+np.abs(xx-45)*1.8).astype('float32')
    z[50:,:]-=(yy[50:,:]-50)*(-1.8)
    transform=from_origin(-70.7,-33.0,0.0003,0.0003)
    with MemoryFile() as mem:
        with mem.open(driver='GTiff',height=h,width=w,count=1,dtype='float32',crs='EPSG:4326',transform=transform,nodata=-9999) as ds:
            ds.write(z,1)
        data=mem.read()
    p=box(-70.688,-33.022,-70.683,-33.018)
    out=detectar(p,data,area_min_cauce_ha=1)
    assert out['cantidad_cauces_modelados']>0, out
    assert out['distancia_cauce_modelado_m'] is not None
    assert 'abanicos_candidatos' in out['capas_geojson']
    print('OK',out['cantidad_cauces_modelados'],out['cantidad_salidas_piedemonte_candidatas'])

if __name__=='__main__':test_drenaje_sintetico()
