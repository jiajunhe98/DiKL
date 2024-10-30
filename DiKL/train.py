import torch
import torch.optim as optim
from torch.distributions import Normal, Gumbel
import numpy as np

import os
import yaml
import argparse
from tqdm import tqdm
from types import SimpleNamespace as config

from train_utils import get_network, get_target, get_sample, save_plot_and_check
from models.dm_utils import extract, remove_mean
from loss import dsm_loss, diKL_loss


def parse_args():
    parser = argparse.ArgumentParser(description="Configuration for model training")

    parser.add_argument("--target", type=str, default='mog')
    parser.add_argument("--device", type=str, default='cuda')
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    return args

def main():
    args = parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    
    if args.target == 'mog':
        opt = yaml.safe_load('configs/mog.yaml')
    elif args.target == 'mw':
        opt = yaml.safe_load('configs/mw.yaml')
    elif args.target == 'dw':
        opt = yaml.safe_load('configs/dw.yaml')
    elif args.target == 'lj':
        opt = yaml.safe_load('configs/lj.yaml')
    else:
        raise NotImplementedError
    
    # make dir to save results
    opt.device = args.device
    opt.proj_path = opt.save_path + opt.name

    if os.path.exists(opt.proj_path):
        counter = 1
        # Loop until a non-existing path is found
        while os.path.exists(opt.proj_path):
            opt.proj_path = opt.save_path + opt.name + f"_{counter}"
            counter += 1

    os.makedirs(opt.proj_path, exist_ok=True)
    os.makedirs(opt.proj_path+'/model', exist_ok=True)
    os.makedirs(opt.proj_path+'/plot', exist_ok=True)

    target = get_target(opt)

    lvm, score_model = get_network(opt)
    lvm_optim = optim.Adam(lvm.parameters(), lr=opt.lvm_lr)
    score_optim = optim.Adam(score_model.parameters(), lr=opt.score_lr)

    process = lambda x: remove_mean(x, n_particles=opt.n_particles, n_dimensions=opt.n_dim) if opt.e3 else lambda x: x

    best_d = 100
    for it in tqdm(range(1,opt.max_iter+1)):
        # train score network
        lvm.eval()
        score_model.train()
        Score_loss = []
        for _ in range(opt.score_iter):
            score_optim.zero_grad()
            x = get_sample(lvm, opt, stop_grad=True)
            # dsm loss
            score_loss = dsm_loss(score_model, x, opt)
            score_loss.backward()
            score_optim.step()
            Score_loss.append(score_loss.item())
        
        # train LVM with diffusive rKL
        lvm.train()
        score_model.eval()
        lvm_optim.zero_grad()
        x = get_sample(lvm, opt, stop_grad=False)

        lvm_loss = diKL_loss(score_model, x, process, opt, target)
        if ~(torch.isnan(lvm_loss) | torch.isinf(lvm_loss)):
            lvm_loss.backward()

        torch.nn.utils.clip_grad_norm_(lvm.parameters(), opt.grad_norm_clip)
        lvm_optim.step()

    # plot and save checkpoints
    x_samples = get_sample(lvm, opt, True, 2000)
    d = save_plot_and_check(opt, x_samples, target, plot_file_name=opt.save_path + '/plot/%d.png'%it)
    if d <= best_d:
        best_d = d
        # save ckpt
        torch.save(lvm.state_dict(), opt.save_path + '/model/' + 'LVM.pt')
        torch.save(score_model.state_dict(), opt.save_path + '/model/' + 'SCORE.pt')
        print('TVD %.6f'%d, flush=True)
        
if __name__ == '__main__':
    main()