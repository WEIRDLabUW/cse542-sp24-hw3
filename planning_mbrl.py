import os
import torch
import numpy as np
from torch import nn
from torch import optim
import argparse
import collections
import functools
import math
import time
from typing import Any, Callable, Dict, Optional, Sequence, List
import gym
import mujoco_py
from gym import utils
import torch.nn.functional as F
import copy
from typing import Tuple, Optional, Union
import matplotlib.pyplot as plt
from train_model import train_model
from utils import ReplayBuffer

def plan_model_random_shooting(env, state, ac_size, horizon, model, reward_fn, n_samples_mpc=100):
    # TODO START-random MPC with shooting
    # Hint1: randomly sample actions in the action space
    # Hint2: rollout model based on current state and random action, select the best action that maximize the sum of the reward

    # TODO END
    return best_ac, random_actions[best_ac_idx]


def plan_model_mppi(env, state, ac_size, horizon, model, reward_fn, n_samples_mpc=100, n_iter_mppi=10, gaussian_noise_scales=[1.0, 1.0, 0.5, 0.5, 0.2, 0.2, 0.1, 0.1, 0.01, 0.01]):
    assert len(gaussian_noise_scales) == n_iter_mppi
    # Rolling forward random actions through the model
    state_repeats = torch.from_numpy(np.repeat(state[None], n_samples_mpc, axis=0)).cuda()
    # Sampling random actions in the range of the action space
    random_actions = torch.FloatTensor(n_samples_mpc, horizon, ac_size).uniform_(env.action_space.low[0], env.action_space.high[0]).cuda().float()
    # Rolling forward through the mdoel for horizon steps
    if not isinstance(model, list):
        all_states, all_rewards = rollout_model(model, state_repeats, random_actions, horizon, reward_fn)
    # TODO START-add ensemble MPPI
    # Hint 1: rollout each model and concatenate rewards for each model


    # TODO END



    all_returns = all_rewards.sum(axis=-1)
    # Take first action from best trajectory
    # best_ac_idx = np.argmax(all_rewards.sum(axis=-1))
    # best_ac = random_actions[best_ac_idx, 0] # Take the first action from the best trajectory

    # Run through a few iterations of MPPI

    # TODO START-MPPI
    # Hint1: Compute weights based on exponential of returns
    # Hint2: sample actions based on the weight, and compute average return over models
    # Hint3: if model type is a list, then implement ensemble mppi




    # TODO END

    # Finally take first action from best trajectory
    best_ac_idx = np.argmax(all_rewards.sum(axis=-1))
    best_ac = random_actions[best_ac_idx, 0] # Take the first action from the best trajectory
    return best_ac, random_actions[best_ac_idx]


def rollout_model(
        model,
        initial_states,
        actions,
        horizon,
        reward_fn):
    # Collect the following data
    all_states = []
    all_rewards = []
    curr_state = initial_states # Starting from the initial state
    # TODO START

    # Hint1: concatenate current state and action pairs as the input for the model and predict the next observation
    # Hint2: get the predicted reward using reward_fn()

    # TODO END
    all_states_full = torch.cat([state[:, None, :] for state in all_states], dim=1).cpu().detach().numpy()
    all_rewards_full = torch.cat(all_rewards, dim=-1).cpu().detach().numpy()    
    return all_states_full, all_rewards_full

def planning_agent(env, o_for_agent, model, reward_fn, plan_mode, mpc_horizon=None, n_samples_mpc=None):
    if plan_mode == 'random':
        # Taking random actions
        action = torch.Tensor(env.action_space.sample()[None]).cuda()
    elif plan_mode == 'random_mpc':
        # Taking actions via random shooting + MPC
        action, _ = plan_model_random_shooting(env, o_for_agent, env.action_space.shape[0], mpc_horizon, model,
                                               reward_fn, n_samples_mpc=n_samples_mpc)
    elif plan_mode == 'mppi':
        action, _ = plan_model_mppi(env, o_for_agent, env.action_space.shape[0], mpc_horizon, model, reward_fn,
                                    n_samples_mpc=n_samples_mpc)
    else:
        raise NotImplementedError("Other planning methods not implemented")
    return action

def collect_traj_MBRL(
        env,
        model,
        plan_mode,
        replay_buffer=None,
        device='cuda:0',
        episode_length=math.inf,
        reward_fn=None, #Reward function to evaluate
        render=False,
        mpc_horizon=None,
        n_samples_mpc=None
):
    # Collect the following data
    raw_obs = []
    raw_next_obs = []
    actions = []
    rewards = []
    dones = []
    images = []

    path_length = 0
    o = env.reset()
    if render:
        env.render()

    while path_length < episode_length:
        o_for_agent = o

        # Using the planning agent to take actions
        action = planning_agent(env, o_for_agent, model, reward_fn, plan_mode, mpc_horizon=mpc_horizon, n_samples_mpc=n_samples_mpc)
        action= action.cpu().detach().numpy()[0]

        # Step the simulation forward
        next_o, r, done, env_info = env.step(copy.deepcopy(action))
        if replay_buffer is not None:
            replay_buffer.add(o,
                            action,
                            r,
                            next_o,
                            done)
        # Render the environment
        if render:
            env.render()

        raw_obs.append(o)
        raw_next_obs.append(next_o)
        actions.append(action)
        rewards.append(r)
        dones.append(done)
        path_length += 1
        if done:
            break
        o = next_o

    # Prepare the items to be returned
    observations = np.array(raw_obs)
    next_observations = np.array(raw_next_obs)
    actions = np.array(actions)
    if len(actions.shape) == 1:
        actions = np.expand_dims(actions, 1)
    rewards = np.array(rewards)
    if len(rewards.shape) == 1:
        rewards = rewards.reshape(-1, 1)
    dones = np.array(dones).reshape(-1, 1)

    # Return in the following format
    return dict(
        observations=observations,
        next_observations=next_observations,
        actions=actions,
        rewards=rewards,
        dones=np.array(dones).reshape(-1, 1),
        images=np.array(images)
    )

# Training loop for policy gradient
def simulate_mbrl(env, model, plan_mode, num_epochs=200, max_path_length=200, mpc_horizon=10, n_samples_mpc=200, 
                  batch_size=100, num_agent_train_epochs_per_iter=1000, capacity=100000, num_traj_per_iter=100, gamma=0.99, print_freq=10, device = "cuda", reward_fn=None):

    # Set up optimizer and replay buffer
    if not isinstance(model, list):
        optimizer = optim.Adam(model.parameters(), lr=1e-4)

    else:
        print('Initialize separate optimizers for ensemble mbrl')
        # TODO START
        # Hint: try using separate optimizer with different learning rate for each model.
        # TODO END
    replay_buffer = ReplayBuffer(obs_size = env.observation_space.shape[0],
                                 action_size = env.action_space.shape[0], 
                                 capacity=capacity, 
                                 device=device)

    # Iterate through data collection and planning loop
    for iter_num in range(num_epochs):
        # Sampling trajectories
        sample_trajs = []
        if iter_num == 0:
            # Seed with some initial data, collecting with mode random
            for it in range(num_traj_per_iter):
                sample_traj = collect_traj_MBRL(env=env,
                                                model=model,
                                                plan_mode='random',
                                                replay_buffer=replay_buffer,
                                                device=device,
                                                episode_length=max_path_length,
                                                reward_fn=reward_fn, #Reward function to evaluate
                                                render=False,
                                                mpc_horizon=None,
                                                n_samples_mpc=None)
                sample_trajs.append(sample_traj)
        else:
            for it in range(num_traj_per_iter):
                sample_traj = collect_traj_MBRL(env=env,
                                                model=model,
                                                plan_mode=plan_mode,
                                                replay_buffer=replay_buffer,
                                                device=device,
                                                episode_length=max_path_length,
                                                reward_fn=reward_fn, #Reward function to evaluate
                                                render=False,
                                                mpc_horizon=mpc_horizon,
                                                n_samples_mpc=n_samples_mpc)
                sample_trajs.append(sample_traj)

        # Train the model
        train_model(model, replay_buffer, optimizer, num_epochs=num_agent_train_epochs_per_iter, batch_size=batch_size)

        # Logging returns occasionally
        if iter_num % print_freq == 0:

            rewards_np = np.mean(np.asarray([traj['rewards'].sum() for traj in sample_trajs]))
            path_length = np.max(np.asarray([traj['rewards'].shape[0] for traj in sample_trajs]))
            print("Episode: {}, reward: {}, max path length: {}".format(iter_num, rewards_np, path_length))