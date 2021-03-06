# -*- coding: utf-8 -*-
from os import makedirs
from os.path import exists, join, pardir, abspath
from json import dump
import time
from datetime import datetime
import torch
from torch.autograd import Variable
from numpy import mean, var

from pc_environment import Env
from pc_model import ActorCritic
from pc_utils import ACTION_SIZE, action_to_one_hot, extend_input, plot_line


def test(rank, args, T, shared_model):
  torch.manual_seed(args.seed + rank)

  env = Env(rank)
  model = ActorCritic(args.hidden_size)
  model.eval()

  can_test = True  # Test flag
  t_start = 1  # Test step counter to check against global counter
  rewards, steps, accs = [], [], []  # Rewards and steps for plotting
  l = str(len(str(args.T_max)))  # Max num. of digits for logging steps
  done = True  # Start new episode

  while T.value() <= args.T_max:
    if can_test:
      t_start = T.value()  # Reset counter

      # Evaluate over several episodes and average results
      avg_rewards, avg_episode_lengths, avg_accs = [], [], []
      for _ in range(args.evaluation_episodes):
        while True:
          # Reset or pass on hidden state
          if done:
            # Sync with shared model every episode
            model.load_state_dict(shared_model.state_dict())
            hx = Variable(torch.zeros(1, args.hidden_size), volatile=True)
            cx = Variable(torch.zeros(1, args.hidden_size), volatile=True)
            # Reset environment and done flag
            state = env.reset()
            action, reward, done, episode_length = 0, 0, False, 0
            reward_sum, class_acc = 0, 0

          # Optionally render validation states
          if args.render:
            env.render()

          # Get label from the environment
          cls_id = env.get_class_label()

          # Calculate policy
          input = extend_input(state, action_to_one_hot(action, ACTION_SIZE), reward, episode_length)
          policy1, _, _, policy2, _, _, cls, (hx, cx) = model(Variable(input, volatile=True), (hx.detach(), cx.detach()))
          cls = cls.data[0, 0] < 0.5 and 0 or 1
          policy = policy1 if cls == 0 else policy2

          # Choose action greedily
          action = policy.max(1)[1].data[0, 0]

          # Step
          state, reward, done, _ = env.step(action)
          reward_sum += reward
          class_acc += cls == cls_id and 1 or 0
          done = done or episode_length >= args.max_episode_length  # Stop episodes at a max length
          episode_length += 1  # Increase episode counter

          # Log and reset statistics at the end of every episode
          if done:
            avg_rewards.append(reward_sum)
            avg_episode_lengths.append(episode_length)
            avg_accs.append(class_acc / episode_length)  # Normalise accuracy by episode length
            break

      print(('[{}] Step: {:<' + l + '} Avg. Reward: {:<8} Avg. Episode Length: {:<8} Avg. Class Acc.: {:<8}').format(
            datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3],
            t_start,
            sum(avg_rewards) / args.evaluation_episodes,
            sum(avg_episode_lengths) / args.evaluation_episodes,
            sum(avg_accs) / args.evaluation_episodes))
      rewards.append(avg_rewards)  # Keep all evaluations
      accs.append(avg_accs)
      # Keep all evaluations
      steps.append(t_start)
      plot_line(steps, rewards, 'rewards.html', 'Average Reward')  # Plot rewards
      plot_line(steps, accs, 'accs.html', 'Average Accuracy')  # Plot accuracy
      torch.save(model.state_dict(), 'checkpoints/' + str(t_start) + '.pth')  # Checkpoint model params
      can_test = False  # Finish testing
      if args.evaluate:
        return
    else:
      if T.value() - t_start >= args.evaluation_interval:
        can_test = True

    time.sleep(0.001)  # Check if available to test every millisecond

  env.close()
