from typing import TypeVar
import dataclasses
import configparser
import os.path as osp

homedir = osp.join(osp.expanduser('~'),'kindle_scan')

@dataclasses.dataclass
class KindleSSConfig:
    window_title : str = 'Kindle'
    execute_filename : str = 'KINDLE.EXE'
    nextpage_key : str = 'left'
    fullscreen_key : str = 'f11'
    pagejump_key : list = dataclasses.field(default_factory=lambda: ['ctrl','g'])

    pagejump : str = '1'

    short_wait : float = 0.1
    long_wait : float = 0.2
    capture_wait : float = 0.35
    timeout_wait : float = 5.0
    fullscreen_wait : float = 2.0

    left_margin : int = 0
    right_margin : int = 0

    base_save_folder : str = homedir
    overwrite : bool = True
    trim_after_capture : bool = False
    force_move_first_page : bool = True
    auto_title : bool = True

    file_extension : str = '.png'
    grayscale_threshold : int = 2

    grayscale_margin_top : int = 1
    grayscale_margin_bottom : int = 16
    grayscale_margin_left : int = 1
    grayscale_margin_right : int = 1

    trim_margin_top : int = 1
    trim_margin_bottom : int = 16
    trim_margin_left : int = 1
    trim_margin_right : int = 1

def key_combination(strk : str)->list:
    lst = strk.split('+')
    return [i.strip() for i in lst]

def file_extension(ext : str)->str:
    return ext if ext[0] == '.' else '.' + ext

special_function = { 'pagejump_key' : key_combination , 'file_extension' : file_extension }
default_ini_name = 'kindless.ini'
default_section = 'KINDLESS'

DataClass = TypeVar('DataClass', bound= KindleSSConfig)

#
#
def read_config(dc: DataClass, ini: str)-> DataClass:
    if not osp.exists(ini):
        raise FileNotFoundError('ini file not found')

    section_name = default_section

    config = configparser.ConfigParser()
    config.read(ini, encoding= 'utf-8')
        
    for k, attr in dc.__annotations__.items():
        if k in special_function.keys():
            try:
                setattr(dc, k, special_function[k]( config.get( section_name, k ))) 
            except configparser.NoOptionError as e:
                print('WARNING : {} NO OPTION'.format(k))
                pass
        else:
            try:
                if attr is int:
                    setattr(dc, k, config.getint( section_name, k))
                elif attr is float:
                    setattr(dc, k, config.getfloat( section_name, k))
                elif attr is bool:
                    setattr(dc, k, config.getboolean( section_name, k))
                elif attr is str:
                    setattr(dc, k, config.get( section_name, k))
            except configparser.NoOptionError as e:
                print('WARNING : {} NO OPTION'.format(k))
    return dc