import os
from os import path

import yaml

import geopandas as gpd
import pandas as pd

from mapshader.colors import colors
from mapshader.io import load_raster
from mapshader.io import load_vector
from mapshader.transforms import get_transform_by_name


class MapSource(object):

    def __init__(self,
                 name=None,
                 description=None,
                 filepath=None,
                 config_path=None,
                 data=None,
                 geometry_type=None,
                 key=None,
                 text=None,
                 fields=None,
                 span=None,
                 route=None,
                 geometry_field='geometry',
                 xfield='geometry',
                 yfield='geometry',
                 zfield=None,
                 agg_func=None,
                 raster_interpolate='linear',
                 shade_how='linear',
                 cmap=colors['viridis'],
                 dynspread=None,
                 extras=None,
                 raster_padding=0,
                 service_types=None,
                 default_extent=None,
                 default_height=256,
                 default_width=256,
                 overviews=None,
                 transforms=None):

        if fields is None and isinstance(data, (pd.DataFrame, gpd.GeoDataFrame)):
            fields = [dict(key=c, text=c, value=c) for c in data.columns if c != geometry_field]

        if extras is None:
            extras = []

        if transforms is None:
            transforms = []

        if overviews is None:
            overviews = []

        if service_types is None:
            service_types = ('tile', 'image', 'wms', 'geojson')

        if span == 'min/max' and zfield is None and geometry_type != 'raster':
            raise ValueError('You must include a zfield for min/max scan calculation')

        if default_extent is None:
            default_extent = [-20e6, -20e6, 20e6, 20e6]

        self.name = name
        self.description = description
        self.filepath = filepath
        self.config_path = config_path
        self.geometry_type = geometry_type
        self.key = key
        self.text = text
        self.fields = fields
        self.span = span
        self.route = route
        self.xfield = xfield
        self.raster_padding = 0
        self.yfield = yfield
        self.zfield = zfield
        self.agg_func = agg_func
        self.overviews = []
        self.raster_agg_func = raster_interpolate
        self.shade_how = shade_how
        self.cmap = cmap
        self.dynspread = dynspread
        self.extras = extras
        self.service_types = service_types
        self.transforms = transforms
        self.default_extent = default_extent
        self.default_width = default_width
        self.default_height = default_height

        self.overviews = overviews
        self._is_loaded = False

        self.data = data

        if data is not None:
            self._is_loaded = True

    @property
    def load_func(self):
        raise NotImplementedError()

    @property
    def is_loaded(self):
        return self._is_loaded

    def load(self):

        if self._is_loaded:
            return self

        if self.config_path:
            ogcwd = os.getcwd()
            config_dir = path.abspath(path.dirname(self.config_path))
            os.chdir(config_dir)
            try:
                data_path = path.abspath(path.expanduser(self.filepath))
            finally:
                os.chdir(ogcwd)

        if self.filepath.startswith('zip'):
            data_path = self.filepath

        elif not path.isabs(self.filepath):
            data_path = path.abspath(path.expanduser(self.filepath))

        else:
            data_path = self.filepath

        self.data = self.load_func(data_path)
        self.apply_transforms()

        return self

    def apply_transforms(self):
        for trans in self.transforms:
            transform_name = trans['name']
            func = get_transform_by_name(transform_name)
            args = trans.get('args', {})
            if transform_name == 'build_raster_overviews':
                self.overviews = func(self.data, **args)
            else:
                self.data = func(self.data, **args)
        return self

    @staticmethod
    def from_obj(obj: dict):
        if obj['geometry_type'] == 'raster':
            return RasterSource(**obj)
        else:
            return VectorSource(**obj)


class RasterSource(MapSource):

    @property
    def load_func(self):
        return load_raster


class VectorSource(MapSource):

    @property
    def load_func(self):
        return load_vector


class MapService():

    def __init__(self, source: MapSource, renderers=[]):
        self.source = source
        self.renderers = renderers

    @property
    def key(self):
        return f'{self.source.key}-{self.service_type}'

    @property
    def name(self):
        return f'{self.source.name} {self.service_type}'

    @property
    def default_extent(self):
        return self.source.default_extent

    @property
    def default_width(self):
        return self.source.default_width

    @property
    def default_height(self):
        return self.source.default_height

    @property
    def service_page_url(self):
        return f'/{self.key}'

    @property
    def service_page_name(self):
        return f'/{self.key}-{self.service_type}'

    @property
    def service_url(self):
        raise NotImplementedError()

    @property
    def client_url(self):
        raise NotImplementedError()

    @property
    def default_url(self):
        raise NotImplementedError()

    @property
    def service_type(self):
        raise NotImplementedError()


class TileService(MapService):

    @property
    def service_url(self):
        return f'/{self.key}' + '/tile/<z>/<x>/<y>'

    @property
    def client_url(self):
        return f'/{self.key}' + '/tile/{z}/{x}/{y}'

    @property
    def default_url(self):
        return f'/{self.key}' + '/tile/0/0/0'

    @property
    def service_type(self):
        return 'tile'


class ImageService(MapService):

    @property
    def service_url(self):
        url = (f'/{self.key}'
               '/image'
               '/<xmin>/<ymin>/<xmax>/<ymax>'
               '/<width>/<height>')
        return url

    @property
    def client_url(self):
        return f'/{self.key}' + '/image/{XMIN}/{YMIN}/{XMAX}/{YMAX}/{width}/{height}'

    @property
    def default_url(self):
        xmin = self.default_extent[0]
        ymin = self.default_extent[1]
        xmax = self.default_extent[2]
        ymax = self.default_extent[3]
        width = self.default_width
        height = self.default_height
        return f'/{self.key}/image/{xmin}/{ymin}/{xmax}/{ymax}/{width}/{height}'

    @property
    def service_type(self):
        return 'image'

class WMSService(MapService):

    @property
    def service_url(self):
        url = f'/{self.key}/wms'
        return url

    @property
    def client_url(self, width=256, height=256):
        url = f'/{self.key}'
        url += '?bbox={XMIN},{YMIN},{XMAX},{YMAX}'
        url += f'&width={width}&height={height}'
        return url

    @property
    def default_url(self):
        xmin = self.default_extent[0]
        ymin = self.default_extent[1]
        xmax = self.default_extent[2]
        ymax = self.default_extent[3]
        width = self.default_width
        height = self.default_height
        return f'/{self.key}?bbox={xmin},{ymin},{xmax},{ymax}&width={width}&height={height}'

    @property
    def service_type(self):
        return 'wms'


class GeoJSONService(MapService):

    @property
    def service_url(self):
        url = f'/{self.key}/geojson'
        return url

    @property
    def client_url(self):
        url = f'/{self.key}/geojson'
        return url

    @property
    def default_url(self):
        return f'/{self.key}/geojson'

    @property
    def service_type(self):
        return 'geojson'


# ----------------------------------------------------------------------------
# DEFAULT MAP SOURCES
# ----------------------------------------------------------------------------

def world_countries_source():

    # construct transforms
    select_by_attrs_transform = dict(name='select_by_attributes',
                                     args=dict(field='name',
                                               value=['Antarctica', 'Fr. S. Antarctic Lands'],
                                               operator='NOT IN'))
    reproject_transform = dict(name='reproject_vector', args=dict(epsg=3857))
    sp_transform = dict(name='to_spatialpandas', args=dict(geometry_field='geometry'))
    transforms = [select_by_attrs_transform,
                  reproject_transform,
                  sp_transform]

    # construct value obj
    source_obj = dict()
    source_obj['name'] = 'World Countries'
    source_obj['key'] = 'world-countries'
    source_obj['text'] = 'World Countries'
    source_obj['description'] = 'World Country Polygons'
    source_obj['geometry_type'] = 'polygon'
    source_obj['agg_func'] = 'max'
    source_obj['shade_how'] = 'linear'
    source_obj['cmap'] = ['black', 'black']
    source_obj['dynspread'] = 2
    source_obj['span'] = 'min/max'
    source_obj['raster_interpolate'] = 'linear'
    source_obj['xfield'] = 'x'
    source_obj['yfield'] = 'y'
    source_obj['zfield'] = 'pop_est'
    source_obj['filepath'] = gpd.datasets.get_path('naturalearth_lowres')
    source_obj['transforms'] = transforms
    source_obj['service_types'] = ['tile', 'wms', 'image', 'geojson']

    return source_obj


def world_boundaries_source():

    # construct transforms
    select_by_attrs_transform = dict(name='select_by_attributes',
                                     args=dict(field='name',
                                               value=['Antarctica', 'Fr. S. Antarctic Lands'],
                                               operator='NOT IN'))
    reproject_transform = dict(name='reproject_vector', args=dict(epsg=3857))
    polygon_to_line_transform = dict(name='polygon_to_line', args=dict(geometry_field='geometry'))
    geopandas_line_to_datashader_line_transform = dict(name='geopandas_line_to_datashader_line',
                                                       args=dict(geometry_field='geometry'))
    transforms = [select_by_attrs_transform,
                  reproject_transform,
                  polygon_to_line_transform,
                  geopandas_line_to_datashader_line_transform]

    # construct value obj
    source_obj = dict()
    source_obj['name'] = 'World Boundaries'
    source_obj['key'] = 'world-boundaries'
    source_obj['text'] = 'World Boundaries'
    source_obj['description'] = 'World Country Boundaries'
    source_obj['geometry_type'] = 'line'
    source_obj['agg_func'] = 'max'
    source_obj['shade_how'] = 'linear'
    source_obj['cmap'] = ['black', 'black']
    source_obj['dynspread'] = 2
    source_obj['raster_interpolate'] = 'linear'
    source_obj['xfield'] = 'x'
    source_obj['yfield'] = 'y'
    source_obj['filepath'] = gpd.datasets.get_path('naturalearth_lowres')
    source_obj['transforms'] = transforms
    source_obj['service_types'] = ['tile', 'wms', 'image', 'geojson']

    return source_obj


def world_cities_source():

    # construct transforms
    reproject_transform = dict(name='reproject_vector', args=dict(epsg=3857))
    add_xy_fields_transform = dict(name='add_xy_fields', args=dict(geometry_field='geometry'))
    sp_transform = dict(name='to_spatialpandas', args=dict(geometry_field='geometry'))
    transforms = [reproject_transform, add_xy_fields_transform, sp_transform]

    # construct value obj
    source_obj = dict()
    source_obj['name'] = 'World Cities'
    source_obj['key'] = 'world-cities'
    source_obj['text'] = 'World Cities'
    source_obj['description'] = 'World Cities Point Locations'
    source_obj['geometry_type'] = 'point'
    source_obj['agg_func'] = 'max'
    source_obj['cmap'] = ['aqua', 'aqua']
    source_obj['shade_how'] = 'linear'
    source_obj['dynspread'] = 2
    source_obj['raster_interpolate'] = 'linear'
    source_obj['xfield'] = 'X'
    source_obj['yfield'] = 'Y'
    source_obj['filepath'] = gpd.datasets.get_path('naturalearth_cities')
    source_obj['transforms'] = transforms
    source_obj['service_types'] = ['tile', 'wms', 'image', 'geojson']

    return source_obj


def nybb_source():

    # construct transforms
    reproject_transform = dict(name='reproject_vector', args=dict(epsg=3857))
    sp_transform = dict(name='to_spatialpandas', args=dict(geometry_field='geometry'))
    transforms = [reproject_transform, sp_transform]

    # construct value obj
    source_obj = dict()
    source_obj['name'] = 'NYC Admin'
    source_obj['key'] = 'nyc-boroughs'
    source_obj['text'] = 'NYC Boroughs'
    source_obj['description'] = 'New York City Boroughs'
    source_obj['geometry_type'] = 'polygon'
    source_obj['agg_func'] = 'max'
    source_obj['shade_how'] = 'linear'
    source_obj['span'] = 'min/max'
    source_obj['dynspread'] = None
    source_obj['raster_interpolate'] = 'linear'
    source_obj['xfield'] = 'geometry'
    source_obj['yfield'] = 'geometry'
    source_obj['zfield'] = 'BoroCode'
    source_obj['filepath'] = gpd.datasets.get_path('nybb')
    source_obj['transforms'] = transforms
    source_obj['service_types'] = ['tile', 'wms', 'image', 'geojson']

    return source_obj


def elevation_source():

    # find data path
    HERE = path.abspath(path.dirname(__file__))
    FIXTURES_DIR = path.join(HERE, 'tests', 'fixtures')
    elevation_path = path.join(FIXTURES_DIR, 'elevation.tif')

    # construct transforms
    squeeze_transform = dict(name='squeeze', args=dict(dim='band'))
    cast_transform = dict(name='cast', args=dict(dtype='float64'))
    orient_transform = dict(name='orient_array')
    flip_transform = dict(name='flip_coords', args=dict(dim='y'))
    reproject_transform = dict(name='reproject_raster', args=dict(epsg=3857))
    transforms = [squeeze_transform,
                  cast_transform,
                  orient_transform,
                  flip_transform,
                  reproject_transform]

    # construct value obj
    source_obj = dict()
    source_obj['name'] = 'Elevation'
    source_obj['key'] = 'elevation'
    source_obj['text'] = 'Elevation'
    source_obj['description'] = 'Global Elevation Dataset'
    source_obj['geometry_type'] = 'raster'
    source_obj['shade_how'] = 'linear'
    source_obj['span'] = 'min/max'
    source_obj['raster_interpolate'] = 'linear'
    source_obj['xfield'] = 'geometry'
    source_obj['yfield'] = 'geometry'
    source_obj['filepath'] = elevation_path
    source_obj['transforms'] = transforms
    source_obj['service_types'] = ['tile', 'wms', 'image', 'geojson']

    return source_obj


def parse_sources(source_objs, config_path=None):

    service_classes = {
        'tile': TileService,
        'wms': WMSService,
        'image': ImageService,
        'geojson': GeoJSONService,
    }

    for source in source_objs:
        for service_type in source['service_types']:
            source['config_path'] = config_path

            # create sources
            source_obj = MapSource.from_obj(source).load()

            # create services
            ServiceKlass = service_classes[service_type]

            # TODO: add renderers here...
            yield ServiceKlass(source=source_obj)


def get_services(config_path=None, include_default=True):

    source_objs = None

    if config_path is None:
        source_objs = [world_countries_source(),
                       world_boundaries_source(),
                       world_cities_source(),
                       nybb_source(),
                       elevation_source()]
    else:
        with open(config_path, 'r') as f:
            content = f.read()
            config_obj = yaml.load(content)
            source_objs = config_obj['sources']

        if include_default:
            source_objs += [world_countries_source(),
                            world_boundaries_source(),
                            world_cities_source(),
                            nybb_source(),
                            elevation_source()]

    for service in parse_sources(source_objs, config_path=config_path):
        yield service
