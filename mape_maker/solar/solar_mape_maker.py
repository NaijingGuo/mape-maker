from pvlib import location
from pvlib import irradiance
import pandas as pd
from matplotlib import pyplot as plt
import numpy as np
from mape_maker.__main__ import main as mapemain
import sys
from argparse import Namespace
from argparse import ArgumentParser
import numpy as np
import glob
import shutil
import os


def get_irradiance(site_location, tilt, surface_azimuth, times):
    clearsky = site_location.get_clearsky(times)
    solar_position = site_location.get_solarposition(times)
    POA_irradiance = irradiance.get_total_irradiance(
        surface_tilt=tilt,
        surface_azimuth=surface_azimuth,
        dni=clearsky['dni'],
        ghi=clearsky['ghi'],
        dhi=clearsky['dhi'],
        solar_zenith=solar_position['apparent_zenith'],
        solar_azimuth=solar_position['azimuth'])
    return pd.DataFrame(POA_irradiance['poa_global'])


def div(list1, list2):
    output = []
    for (i, j) in zip(list1, list2):
        if isinstance(i, int) or isinstance(i, float):
            if j == 0:
                output.append(0)
            else:
                output.append(i/j)
        else:
            print('Input is not a list of numbers')
            break
    return output


def flatten(t):
    out = []
    for sublist in t:
        if isinstance(sublist, float):
            out.append(sublist)
        else:
            for item in sublist:
                out.append(item)
    return out


def deviation(start_time, end_time, location_coor, input_solar_file, x_name):
    try:
        obs = pd.read_csv(input_solar_file)
    except:
        raise ValueError('Invalid input solar file name')
    obs = obs.set_index(pd.DatetimeIndex(pd.to_datetime(obs['datetime'])))
    obs = obs.iloc[:, 1:]
    if start_time == None:
        start_time = str(obs.index[0])
    if end_time == None:
        end_time = str(obs.index[-1])
    start_time = pd.to_datetime(start_time + ' 00:00:00')
    end_time = pd.to_datetime(end_time + ' 00:00:00')
    if (obs.index[0] > start_time) or (obs.index[-1] < end_time):
        raise ValueError('Invalid start or end date. The input file has date range {} to {}'.format(
            obs.index[0], obs.index[-1]))
    obs = obs[(obs.index >= start_time)
              & (obs.index < end_time)]
    cap = max(obs[x_name])
    times = pd.date_range(start=start_time,
                          end=end_time, freq='60min', closed='left')
    location_coor = list(location_coor[0].split())
    for i in range(len(location_coor)):
        location_coor[i] = int(location_coor[i])
    length = int(len(location_coor))
    POA = pd.DataFrame()
    for i in range(int(length/2)):
        lat = location_coor[2*i]
        lon = location_coor[2*i+1]
        site = location.Location(lat, lon)
        POA_single = get_irradiance(site, 15, 180, times)
        POA = pd.concat([POA, POA_single], axis=1)
        POA = POA.max(axis=1)
        POA = POA.to_frame()
        POA.rename(columns={POA.columns[0]: "poa_global"}, inplace=True)
        n = POA.size

    # calculate csi
    norm_max = POA.max()
    csi = POA.div(norm_max)
    max_csi_d = []
    for i in range(int(n/24)):
        max_csi_d.append(float(csi.iloc[i*24:i*24+24].max().values))
        csi_list = csi['poa_global'].tolist()
        csi_list = flatten(csi_list)

    # calculate p
    max_p_d = []
    forecast = obs.iloc[:, 0]
    forecast = forecast.to_frame()
    actual = obs.iloc[:, 1]
    actual_list = actual.tolist()
    actual = actual.to_frame()
    for i in range(int(n/24)):
        max_p_d.append(float(actual.iloc[i*24:i*24+24].max()))

    # calculate G
    G = div(max_p_d, max_csi_d)
    # make G non-decreasing
    for i in range(len(G)-1):
        if G[i+1] < G[i]:
            G[i+1] = G[i]

    # calculate T
    T = []
    interm = div(actual_list, csi_list)
    for i in range(int(n/24)):
        T.append(max(interm[i*24: i*24+24])/G[i])
    upper = []
    for i in range(int(n/24)):
        for j in range(24):
            upper.append(G[i]*min(max_csi_d[i], T[i]*csi_list[i*24+j]))
    upper_df = pd.DataFrame(upper, index=times, columns=['upper bound'])
    upper_df.index.name = 'datetimes'
    forecast_div = upper_df.values-forecast.values
    deviation_df = pd.DataFrame(
        forecast_div, index=times, columns=['forecasts'])
    deviation_df['actuals'] = upper_df.values-actual.values
    deviation_df.to_csv('deviation.csv')  # input for mape_maker, needed
    return upper_df, cap


def make_parser():
    parser = ArgumentParser()
    parser.add_argument('-so', '--solar_output_dir',
                        help='path to a directory to save the simulations',
                        type=str,
                        default=None)
    parser.add_argument('-isf', '--input_solar_file',
                        help='input solar file for simulation',
                        type=str,
                        required=True)
    parser.add_argument('-sf', '--input_sid_file',
                        help='second input file for simulation,\
                         from which scenarios for the other timeseries are generated',
                        type=str,
                        default=None)
    parser.add_argument('-is', '--input_start_time',
                        help='start time for computation of the distribution. If None, start from the beginning of the input file.',
                        type=str, default=None)
    parser.add_argument('-ie', '--input_end_time',
                        help='end time for computation of the distribution',
                        type=str,
                        default=None)
    parser.add_argument('-ss', '--simulation_start_time',
                        help='start time for simulation',
                        type=str,
                        default=None)
    parser.add_argument('-se', '--simulation_end_time',
                        help='end time for simulation',
                        type=str,
                        default=None)
    parser.add_argument('-t', '--target_mape',
                        help='mape you want in return, otherwise will take the mape of the dataset',
                        type=float,
                        default=None)
    parser.add_argument('-a', '--a',
                        help='percent of data for the estimation',
                        type=float,
                        default=4)
    parser.add_argument('-n', '--simulations_num',
                        help='number of simulations',
                        type=int,
                        default=1)
    parser.add_argument('-ct', '--curvature_target',
                        help='target of the second difference',
                        type=float,
                        default=None)
    parser.add_argument('-m', '--mip_gap',
                        help='the curvature mip gap',
                        type=float,
                        default=0.3)
    parser.add_argument('-vo', '--verbosity_output',
                        help='the output file to save the verbosity',
                        type=str,
                        default=None)
    parser.add_argument('-tl', '--time_limit',
                        help='time limit for computing curvature',
                        type=int,
                        default=3600)
    parser.add_argument('-ps', '--plot_start_date',
                        help='start date to plot the result',
                        type=int,
                        default=0)
    parser.add_argument('-s', '--seed',
                        help='seed for simulation',
                        type=int,
                        default=None)
    parser.add_argument('-v', '--verbosity',
                        help='verbosity level',
                        type=int,
                        default=2)
    parser.add_argument('-f', '--sid_feature',
                        help='feature for simulation',
                        choices=['actuals', 'forecasts'],
                        default='actuals')
    parser.add_argument('-bp', '--base_process',
                        help='method used',
                        choices=['iid', 'ARMA'],
                        default='ARMA')
    parser.add_argument('-lp', '--load_pickle',
                        help='load pickle file instead of estimating',
                        default=False,
                        action='store_true')
    parser.add_argument('-c', '--curvature',
                        help='curvature',
                        default=False,
                        action='store_true')
    parser.add_argument('-sh', '--show_curv_model',
                        help='show model of curvature',
                        default=False,
                        action='store_true')
    # plot for solar, the original plot (for deviation) is disabled here
    parser.add_argument('-sp', '--solar_plot',
                        help='solar plot simulations',
                        default=False,
                        action='store_true')
    parser.add_argument('-sv', '--solver',
                        help='curvature solver',
                        default='gurobi')
    parser.add_argument('-lc', '--location_coordinate',
                        help='one or more pairs of location coordinates. Use space to separate\
                            numbers and enter in the sequence of lat_1 lon_1 lat_2 lon_2...',
                        nargs='+', required=True)
    # target_scale_cap for solar, the original option is disabled here
    parser.add_argument('-sts', '--solar_target_scaled_capacity',
                        help='scale all solar scenario data by target_capacity/capacity',
                        type=float,
                        default=None)
    return parser


def main(args):
    solar_output_dir = args.solar_output_dir
    solar_plot = args.solar_plot
    input_solar_file = args.input_solar_file
    simulations_num = args.simulations_num
    input_start_time = args.input_start_time
    input_end_time = args.input_end_time
    simulation_start_time = args.simulation_start_time
    simulation_end_time = args.simulation_end_time
    location_coor = args.location_coordinate
    solar_target_scaled_capacity = args.solar_target_scaled_capacity
    args.input_xyid_file = 'deviation.csv'
    args.output_dir = 'midstep_output'
    args.title = None
    args.x_legend = None
    args.target_scaled_capacity = None
    args.scale_by_capacity = 0
    # save (then delete) output file from MapeMaker, but do not show on log
    args.use_output_as_intermidiate = True
    args.plot = False
    if args.sid_feature == "actuals":
        x_name = "forecasts"
    elif args.sid_feature == "forecasts":
        x_name = "actuals"
    upper, cap = deviation(input_start_time, input_end_time,
                           location_coor, input_solar_file, x_name)
    upper = upper[(upper.index >= simulation_start_time)
                  & (upper.index < simulation_end_time)]
    mapemain(args)
    filename = glob.glob(args.output_dir+'/'+'*.csv')
    filename = filename[0]
    after_mape = pd.read_csv(filename)
    after_mape.rename(columns={'Unnamed: 0': 'datetime'}, inplace=True)
    after_mape['datetime'] = pd.to_datetime(after_mape['datetime'])
    after_mape.set_index("datetime", inplace=True)
    after_mape = after_mape[(after_mape.index >= simulation_start_time)
                            & (after_mape.index < simulation_end_time)]
    after_mape = -after_mape
    for i in range(simulations_num):
        after_mape.iloc[:, i] = (after_mape.iloc[:, i]+upper['upper bound'])
    if solar_target_scaled_capacity != None:
        after_mape = after_mape * \
            (solar_target_scaled_capacity/cap)
    if solar_plot == True:
        fig = after_mape.plot()
        fig.figure.savefig('results')
    dir = (solar_output_dir)
    if not os.path.exists(dir):
        os.mkdir(dir)
        after_mape.to_csv(dir + '/simulations.csv')
        print('output saved to' + ' ' + solar_output_dir)
    else:
        raise ValueError('Directory already exists.')

    # delete midstep files
    shutil.rmtree(args.output_dir)
    os.remove('deviation.csv')


if __name__ == '__main__':
    parser = make_parser()
    args = parser.parse_args()
    main(args)
 # python -m mape_maker.solar.Solar -isf '/home/naijing/Desktop/work/mape-maker-Naijing/mape_maker/solar/Solar_Taxes_2018.csv' -is '2018-07-01 00:00:00' -ie '2018-12-01 00:00:00' -ss '2018-07-01 00:00:00' -se '2018-07-07 00:00:00' -n 2 -bp 'iid' -lc 37 -103 31 -94 26 -98 32 -107 -so 'solar_test_output' -sp
