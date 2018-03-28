#!python
from collections import OrderedDict

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable

from pyro.nn import ClippedSoftmax

from ..utils import params as p


class View(nn.Module):

    def __init__(self, dim):
        super().__init__()
        self.dim = dim

    def forward(self, x, *args):
        return x.view(*self.dim)


class Swish(nn.Module):

    def forward(self, x):
        return x * F.sigmoid(x)


class _DenseLayer(nn.Sequential):

    def __init__(self, num_input_features, growth_rate, bn_size, drop_rate):
        super().__init__()
        self.add_module("norm.1", nn.BatchNorm2d(num_input_features)),
        self.add_module("swish.1", Swish()),
        self.add_module("conv.1", nn.Conv2d(num_input_features, bn_size *
                        growth_rate, kernel_size=1, stride=1, bias=False)),
        self.add_module("norm.2", nn.BatchNorm2d(bn_size * growth_rate)),
        self.add_module("swish.2", Swish()),
        self.add_module("conv.2", nn.Conv2d(bn_size * growth_rate, growth_rate,
                        kernel_size=3, stride=1, padding=1, bias=False)),
        self.drop_rate = drop_rate

    def forward(self, x):
        new_features = super().forward(x)
        if self.drop_rate > 0:
            new_features = F.dropout(new_features, p=self.drop_rate, training=self.training)
        return torch.cat([x, new_features], 1)


class _DenseBlock(nn.Sequential):

    def __init__(self, num_layers, num_input_features, bn_size, growth_rate, drop_rate):
        super().__init__()
        for i in range(num_layers):
            layer = _DenseLayer(num_input_features + i * growth_rate, growth_rate, bn_size, drop_rate)
            self.add_module(f"denselayer{i+1}", layer)


class _Transition(nn.Sequential):

    def __init__(self, num_input_features, num_output_features):
        super().__init__()
        self.add_module("norm", nn.BatchNorm2d(num_input_features))
        self.add_module("swish", Swish())
        self.add_module("conv", nn.Conv2d(num_input_features, num_output_features,
                                          kernel_size=1, stride=1, bias=False))
        self.add_module("pool", nn.AvgPool2d(kernel_size=3, stride=2, padding=1))


class DenseNet(nn.Module):
    r"""Densenet-BC model class, based on
    `"Densely Connected Convolutional Networks" <https://arxiv.org/pdf/1608.06993.pdf>`_

    Args:
        growth_rate (int) - how many filters to add each layer (`k` in paper)
        block_config (list of 4 ints) - how many layers in each pooling block
        num_init_features (int) - the number of filters to learn in the first convolution layer
        bn_size (int) - multiplicative factor for number of bottle neck layers
          (i.e. bn_size * k features in the bottleneck layer)
        drop_rate (float) - dropout rate after each dense layer
    """
    def __init__(self, x_dim=p.NUM_PIXELS, y_dim=p.NUM_LABELS, growth_rate=4, block_config=(6, 12, 24, 48, 16),
                 num_init_features=64, bn_size=4, drop_rate=0, eps=p.EPS):
        super().__init__()
        self.x_dim = x_dim
        self.y_dim = y_dim
        self.eps = eps
        # First convolution
        self.hidden = nn.Sequential(OrderedDict([
            ("view.i", View(dim=(-1, 2, 129, 21))),
            ("conv.i", nn.Conv2d(2, num_init_features, kernel_size=3, stride=1, padding=1, bias=False)),
            ("norm.i", nn.BatchNorm2d(num_init_features)),
            ("swish.i", Swish()),
            ("pool.i", nn.MaxPool2d(kernel_size=3, stride=(2, 1), padding=1)),
        ]))

        # Each denseblock
        num_features = num_init_features
        for i, num_layers in enumerate(block_config):
            block = _DenseBlock(num_layers=num_layers, num_input_features=num_features,
                                bn_size=bn_size, growth_rate=growth_rate, drop_rate=drop_rate)
            self.hidden.add_module(f"denseblock{i+1}", block)
            num_features = num_features + num_layers * growth_rate
            if i != len(block_config) - 1:
                trans = _Transition(num_input_features=num_features, num_output_features=num_features // 2)
                self.hidden.add_module(f"transition{i+1}", trans)
                num_features = num_features // 2

        # Final layer
        self.hidden.add_module("norm.f", nn.BatchNorm2d(num_features))
        self.hidden.add_module("swish.f", Swish())
        self.hidden.add_module("pool.f", nn.AvgPool2d(kernel_size=2, stride=1))
        self.hidden.add_module("view.f", View(dim=(-1, 195 * 4)))
        self.hidden.add_module("class.f", nn.Linear(195 * 4, y_dim))

        # Official init from torch repo.
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal(m.weight.data)
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()
            elif isinstance(m, nn.Linear):
                m.bias.data.zero_()

    def forward(self, x, softmax=False):
        out = self.hidden(x)
        if softmax:
            return ClippedSoftmax(self.eps, dim=1)(out)
        else:
            return out

    def test(self):
        xs = torch.randn(10, self.x_dim)
        print(xs.shape)
        xs = Variable(xs)
        for h in self.hidden:
            xs = h.forward(xs)
            print(xs.shape)


if __name__ == "__main__":
    print("dense")
    dense = DenseEncoderY(x_dim=p.NUM_PIXELS, y_dim=p.NUM_LABELS)
    dense.test()
