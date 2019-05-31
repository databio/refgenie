#!/usr/bin/env python

from argparse import ArgumentParser
from collections import OrderedDict
from requests import get
from json import loads
import os
import pypiper
import re
import sys
import logmuse
from ._version import __version__

from refgenconf import select_genome_config, RefGenConf
from refgenconf.const import *


_LOGGER = None


# This establishes the API with the server
refgenie_server_api = {
    "list_available_genomes": "/genomes",
    'list_assets_by_genome': "/genome/{genome}",
    'download_asset': "/asset/{genome}/{asset}",
}


class _VersionInHelpParser(ArgumentParser):
    def format_help(self):
        """ Add version information to help text. """
        return "version: {}\n".format(__version__) + \
               super(_VersionInHelpParser, self).format_help()


def build_argparser():
    """
    Builds argument parser.

    :return argparse.ArgumentParser
    """

    banner = "%(prog)s - builds and manages reference genome assemblies"
    additional_description = "\nhttps://refgenie.databio.org"

    parser = _VersionInHelpParser(
        description=banner,
        epilog=additional_description)

    parser.add_argument(
        "-V", "--version",
        action="version",
        version="%(prog)s {v}".format(v=__version__))

    subparsers = parser.add_subparsers(dest="command")

    def add_subparser(cmd, description):
        return subparsers.add_parser(
            cmd, description=description, help=description)

    subparser_messages = {
        "init": "Initialize a genome configuration.",
        "list": "List available local genomes.",
        "listr": "List available genomes and assets on server.",
        "pull": "Download assets.",
        "build": "Build genome assets",
    }

    parser.add_argument('-c', '--genome-config', dest="genome_config")

    sps = {}
    for cmd, desc in subparser_messages.items():
        sps[cmd] = add_subparser(cmd, desc)

    sps["init"].add_argument('-s', '--genome-server', default="http://localhost")
    sps["build"] = pypiper.add_pypiper_args(sps["build"], groups=None, args=["recover"])

    # Add any pipeline-specific arguments
    sps["build"].add_argument('-i', '--input', dest='input', required=True,
                              help='Local path or URL to genome sequence file in .fa, .fa.gz, or .2bit format.')

    sps["build"].add_argument('-n', '--name', dest='name', required=False,
                              help='Name of the genome to build. If omitted, refgenie will use'
                                   'the basename of the file specified in --input.')

    sps["build"].add_argument('-a', '--annotation', dest='annotation', required=False,
                              help='Path to GTF gene annotation file.')

    sps["build"].add_argument("-d", "--docker", action="store_true",
                              help="Run all commands in the refgenie docker container.")

    sps["build"].add_argument('-o', '--outfolder', dest='outfolder', required=False, default=None,
                              help='Override the default path to genomes folder, which is to '
                                   'use the genome_folder attribute in the genome configuration file.')

    sps["pull"].add_argument('-g', '--genome', default="hg38")
    sps["pull"].add_argument('-a', '--asset', default="bowtie2", nargs='+')
    sps["pull"].add_argument("-u", "--unpack", action="store_true", help="Unpack the downloaded archives.",
                             dest="unpack")

    return parser


def copy_or_download_file(input_string, outfolder):
    """
    Given an input file, which can be a local file or a URL, and output folder,
    this downloads or copies the file into the output folder.
    @param input_string: Can be either a URL or a path to a local file
    @type input_string: str
    @param outfolder: Where to store the result.
    """
    result_file = os.path.join(outfolder, os.path.basename(input_string))

    if is_url(input_string):
        cmd = "wget -O " + result_file + " " + input_string
    else:
        cmd = "cp " + input_string + " " + result_file
    return [result_file, cmd]


def convert_file(input_file, output_file, conversions):
    """
    Given an input file, output file, and a list of conversions, gives the appropriate output file.
    @param output_file: Path to local output file you want to create
    @param conversions: A dictionary of shell commands to convert files of a given type.
    @type conversions: dict
    """
    form = {"INPUT": input_file, "OUTPUT": output_file}
    ext = os.path.splitext(input_file)[1]
    if ext in conversions:
        cmd = conversions[ext].format(**form)
        return (cmd)
    else:
        # No conversion available/necessary.
        return None


def default_config_file():
    """
    Path to default compute environment settings file.

    :return str: Path to default compute settings file
    """
    return os.path.join(os.path.dirname(__file__), "refgenie.yaml")


def build_indexes(args):
    if args.name:
        genome_name = args.name
    else:
        genome_name = os.path.basename(args.input)
        # eliminate extensions to get canonical genome name.
        for strike in [".fasta.gz$", ".fa.gz$", ".fasta$", ".fa$", ".gz$", ".2bit$"]:
            genome_name = re.sub(strike, "", genome_name)

    _LOGGER.info("Using genome name: {}".format(genome_name))
    outfolder = os.path.abspath(os.path.join(args.outfolder, genome_name))
    _LOGGER.info("Output to: {} {} {}".format(genome_name, args.outfolder, outfolder))

    _LOGGER.debug("Default config file: {}".format(default_config_file()))

    if args.config_file and not os.path.isfile(args.config_file):
        _LOGGER.debug("Config file path isn't a file: {}".
                      format(args.config_file))
        args.config_file = default_config_file()

    pm = pypiper.PipelineManager(name="refgenie", outfolder=outfolder, args=args)
    tk = pypiper.NGSTk(pm=pm)
    tools = pm.config.tools  # Convenience alias
    index = pm.config.index
    param = pm.config.param

    # pm.make_sure_path_exists(outfolder)
    conversions = {}
    conversions[".2bit"] = "twoBitToFa {INPUT} {OUTPUT}"
    conversions[".gz"] = tk.ziptool + " -cd {INPUT} > {OUTPUT}"

    # Copy fasta file to genome folder structure
    local_raw_fasta = genome_name + ".fa"
    raw_fasta = os.path.join(outfolder, local_raw_fasta)

    input_file, cmd = copy_or_download_file(args.input, outfolder)
    pm.run(cmd, input_file)

    container = None
    if args.docker:
        # Set up some docker stuff
        pm.get_container("nsheff/refgenie", outfolder)
        # of = os.path.abspath(outfolder)
        # outfolder = of
        # cmd = "docker run -itd"
        # cmd += " -v " + of + ":" + of
        # cmd += " nsheff/refgenie"
        # container = pm.checkprint(cmd).rstrip()
        # _LOGGER.info("Using docker container: " + container)
        # pm.atexit_register(remove_container, container)

    cmd = convert_file(input_file, raw_fasta, conversions)
    if cmd:
        pm.run(cmd, raw_fasta, container=pm.container)

    cmd = tools.samtools + " faidx " + raw_fasta
    pm.run(cmd, raw_fasta + ".fai", container=pm.container)

    # Determine chromosome sizes
    fai_file = raw_fasta + ".fai"
    # symlinks should be relative so folders are portable.
    loc_chrom_sizes_file = genome_name + ".chrom.sizes"
    chrom_sizes_file = os.path.join(outfolder, loc_chrom_sizes_file)
    chrom_sizes_alias = os.path.join(outfolder, genome_name + ".chromSizes")
    cmd = "cut -f 1,2 " + fai_file + " > " + chrom_sizes_file
    cmd2 = "ln -s " + loc_chrom_sizes_file + " " + chrom_sizes_alias
    pm.run([cmd, cmd2], chrom_sizes_alias, container=pm.container)

    # Copy annotation file (if any) to folder structure
    if args.annotation:
        annotation_file_unzipped = os.path.join(outfolder, genome_name + ".gtf")
        annotation_file, cmd = copy_or_download_file(args.annotation, outfolder)
        pm.run(cmd, annotation_file)

        cmd = convert_file(annotation_file, annotation_file_unzipped, conversions)
        pm.run(cmd, annotation_file_unzipped)

    #   cmd = "cp " + args.annotation + " " + annotation_file
    #   cmd2 = tk.ziptool + " -d " + annotation_file
    #   pm.run([cmd, cmd2], annotation_file_unzipped)

    else:
        _LOGGER.debug("* No GTF gene annotations provided. Skipping this step.")

    # Bowtie indexes
    if index.bowtie2:
        folder = os.path.join(outfolder, "indexed_bowtie2")
        tk.make_dir(folder)
        target = os.path.join(folder, "completed.flag")
        cmd1 = "ln -sf ../" + local_raw_fasta + " " + folder
        cmd2 = tools.bowtie2build + " " + raw_fasta + " " + os.path.join(folder, genome_name)
        cmd3 = "touch " + target
        pm.run([cmd1, cmd2, cmd3], target, container=pm.container)

    # Bismark index - bowtie2
    if index.bismark_bt2:
        folder = os.path.join(outfolder, "indexed_bismark_bt2")
        tk.make_dir(folder)
        target = os.path.join(folder, "completed.flag")
        cmd1 = "ln -sf ../" + local_raw_fasta + " " + folder
        cmd2 = tools.bismark_genome_preparation + " --bowtie2 " + folder
        cmd3 = "touch " + target
        pm.run([cmd1, cmd2, cmd3], target, container=pm.container)

    # Bismark index - bowtie1
    if index.bismark_bt1:
        folder = os.path.join(outfolder, "indexed_bismark_bt1")
        tk.make_dir(folder)
        target = os.path.join(folder, "completed.flag")
        cmd1 = "ln -sf ../" + local_raw_fasta + " " + folder
        cmd2 = tools.bismark_genome_preparation + " " + folder
        cmd3 = "touch " + target
        pm.run([cmd1, cmd2, cmd3], target, container=pm.container)

    # Epilog meth calling
    if index.epilog:
        folder = os.path.join(outfolder, "indexed_epilog")
        tk.make_dir(folder)
        target = os.path.join(folder, "completed.flag")
        cmd1 = "ln -sf ../" + local_raw_fasta + " " + folder
        cmd2 = tools.epilog_indexer + " -i " + raw_fasta
        cmd2 += " -o " + os.path.join(folder, genome_name + "_" + param.epilog.context + ".tsv")
        cmd2 += " -s " + param.epilog.context  # context
        cmd2 += " -t"
        cmd3 = "touch " + target
        pm.run([cmd1, cmd2, cmd3], target, container=pm.container)

    if index.hisat2:
        folder = os.path.join(outfolder, "indexed_hisat2")
        tk.make_dir(folder)
        target = os.path.join(folder, "completed.flag")
        cmd1 = "ln -sf ../" + local_raw_fasta + " " + folder
        cmd2 = tools.hisat2build + " " + raw_fasta + " " + os.path.join(folder, genome_name)
        cmd3 = "touch " + target
        pm.run([cmd1, cmd2, cmd3], target, container=pm.container)

    # Kallisto should index transcriptome
    # So it doesn't make sense to run these at the same time as the others.
    if index.kallisto:
        folder = os.path.join(outfolder, "indexed_kallisto")
        tk.make_dir(folder)
        target = os.path.join(folder, "completed.flag")
        cmd2 = tools.kallisto + " index -i " + os.path.join(folder, genome_name + "_kallisto_index.idx")
        cmd2 += " " + raw_fasta
        cmd3 = "touch " + target
        pm.run([cmd2, cmd3], target, container=pm.container)

    pm.stop_pipeline()


def _download_json(url):
    """
    Safely connects to the provided API endpoint and downloads the JSON formatted data

    :param str url: server API endpoint
    :return dict: served data
    """
    try:
        _LOGGER.debug("Downloading JSON data; querying URL: '{}'".format(url))
        server_resp = get(url)
        if server_resp.ok:
            json_data = loads(server_resp.content)
    except Exception as e:
        _LOGGER.warning("There was a problem querying the URL: '{}'. Got: {}:{}".format(url, e.__class__.__name__, e))
        json_data = None
    return json_data


def _is_large_archive(size):
    """
    Determines if the file is large based on a string formatted as follows: 15.4GB

    :param str size:  size string
    :return bool: the decision
    """
    _LOGGER.debug("Checking archive size: '{}'".format(size))
    if size.endswith("TB"):
        return True
    if size.endswith("GB"):
        size_numeric = float("".join(list(filter(lambda x: x in '0123456789.', size))))
        if size_numeric > 5:
            return True
    return False


def refgenie_init(genome_config_path, genome_server="http://localhost"):
    """ Initialize genome config """

    # Set up default 
    rgc = RefGenConf(OrderedDict({
        CFG_FOLDER_KEY: os.path.dirname(genome_config_path),
        CFG_SERVER_KEY: genome_server,
        CFG_GENOMES_KEY: None
    }))

    _LOGGER.debug("RGC: {}".format(rgc))

    if genome_config_path and not os.path.exists(genome_config_path):
        rgc.write(genome_config_path)
        _LOGGER.info("Wrote new refgenie genome configuration file: {}".format(genome_config_path))
    else:
        _LOGGER.warning("Can't initialize, file exists: {} ".format(genome_config_path))


def _exec_list(rgc, remote):
    if remote:
        pfx = "Remote"
        assemblies, assets = rgc.list_remote()
    else:
        pfx = "Local"
        assemblies, assets = rgc.genomes_str(), rgc.assets_str()
    return pfx, assemblies, assets


def main():
    """ Primary workflow """

    parser = logmuse.add_logging_options(build_argparser())
    args, remaining_args = parser.parse_known_args()
    global _LOGGER
    _LOGGER = logmuse.logger_via_cli(args)

    _LOGGER.debug("Args: {}".format(args))

    if not args.command:
        parser.print_help()
        _LOGGER.error("No command given")
        sys.exit(1)

    if args.command == "init":
        _LOGGER.info("Initializing refgenie genome configuration")
        refgenie_init(args.genome_config, args.genome_server)
        sys.exit(0)

    genome_config_path = select_genome_config(args.genome_config)
    rgc = RefGenConf(genome_config_path)

    if not rgc:
        parser.print_help()
        _LOGGER.error("Can't load genome configuration file")
        sys.exit(1)

    if args.command == "build":
        build_indexes(args)

    if args.command == "pull":
        rgc.pull_asset(args.genome, args.asset, genome_config_path, args.unpack)

    elif args.command in ["list", "listr"]:
        pfx, genomes, assets = _exec_list(rgc, args.command == "listr")
        _LOGGER.info("{} genomes: {}".format(pfx, genomes))
        _LOGGER.info("{} assets:\n{}".format(pfx, assets))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        _LOGGER.info("Program canceled by user!")
        sys.exit(1)


