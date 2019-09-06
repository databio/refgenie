#!/usr/bin/env python
"""
Each iGenomes has the following nested directory structure:
    Species/
    Source/
    Build/
    Annotation/ Sequence/
"""
from .refgenie import refgenie_add

from ubiquerg import untar, mkabs

import refgenconf
from glob import glob

import os
import argparse
import sys
import tarfile
from shutil import copytree


def build_argparser():
    """
    Build a parser for this tool

    :return argparse.ArgumentParser: constructed parser
    """
    parser = argparse.ArgumentParser(description='Integrates every asset from the downloaded iGenomes'
                                                 ' tarball/directory with Refgenie asset management system')
    parser.add_argument('-p', '--path', dest="path", type=str,  help='path to the desired genome tarball to integrate',
                        required=True)
    parser.add_argument('-g', '--genome', dest="genome", type=str,  help='name to be assigned to the selected genome',
                        required=True)
    parser.add_argument('-c', '--config', dest="config", type=str,  help='genome config', required=True)
    return parser


def untar_or_copy(p, dest):
    """
    Depending on a kind of the provided path, either copy or extract it to the destination directory

    :param str p: path to the directory to be copied or tarball to be extracted
    :param str dest: where to extract file or copy dir
    :return bool: whether the process was successful
    """
    if os.path.exists(p):
        fun = untar if tarfile.is_tarfile(p) else copytree
        fun(p, dest)
        print("Moved '{}' to '{}'".format(p, dest))
        return True
    return False


def main():
    """ main workflow """
    parser = build_argparser()
    args, remaining_args = parser.parse_known_args()
    pths = [args.path, mkabs(args.path)]
    if not untar_or_copy(pths[0], args.genome):
        if not untar_or_copy(pths[1], args.genome):
            raise OSError("Path '{}' does not exist. Tried: {}".format(args.path, " and ".join(pths)))
    rgc = refgenconf.RefGenConf(args.config)
    path_components = [args.genome] + ["*"] * 3 + ["Sequence"]
    assets_paths = glob(os.path.join(*path_components))
    assert len(assets_paths) == 1, OSError("Your iGenomes directory is corrupted, more that one directory matched by {}"
                                           .format(os.path.join(*path_components)))
    assets_path = assets_paths[0]
    asset_names = [d for d in os.listdir(assets_path) if os.path.isdir(assets_path)]
    processed = []
    for a in asset_names:
        asset_dict = {"genome": args.genome, "asset": a, "tag": None, "seek_key": None}
        asset_path = os.path.join(assets_path, a)
        if refgenie_add(rgc, asset_dict, asset_path):
            processed.append("{}/{}".format(asset_dict["genome"], asset_dict["asset"]))
    print("Added assets: \n- {}".format("\n- ".join(processed)))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Program canceled by user!")
        sys.exit(1)
