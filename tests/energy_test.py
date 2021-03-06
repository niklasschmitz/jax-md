# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for google3.third_party.py.jax_md.energy."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from absl.testing import absltest
from absl.testing import parameterized

from jax.config import config as jax_config
from jax import random
import jax.numpy as np

import numpy as onp

from jax.api import grad
from jax_md import space
from jax_md.util import *
from jax_md.test_util import update_test_tolerance
from jax_md import quantity

from jax import test_util as jtu

from jax_md import energy
from jax_md.interpolate import spline

jax_config.parse_flags_with_absl()
FLAGS = jax_config.FLAGS

PARTICLE_COUNT = 100
STOCHASTIC_SAMPLES = 10
SPATIAL_DIMENSION = [2, 3]
UNIT_CELL_SIZE = [7, 8]

SOFT_SPHERE_ALPHA = [2.0, 3.0]

if FLAGS.jax_enable_x64:
  POSITION_DTYPE = [f32, f64]
else:
  POSITION_DTYPE = [f32]

update_test_tolerance(2e-5, 1e-7)


def lattice_repeater(small_cell_pos, latvec, no_rep):
  dtype = small_cell_pos.dtype
  pos = onp.copy(small_cell_pos).tolist()
  for atom in small_cell_pos:
    for i in range(no_rep):
      for j in range(no_rep):
        for k in range(no_rep):
          if not i == j == k == 0:
            repeated_atom = atom + latvec[0] * i + latvec[1] * j + latvec[2] * k
            pos.append(onp.array(repeated_atom).tolist())
  return np.array(pos, dtype), f32(latvec*no_rep)


def make_eam_test_splines():
  cutoff = 6.28721

  num_spline_points = 21
  dr = np.arange(0, num_spline_points) * (cutoff / num_spline_points)
  dr = np.array(dr, f32)

  drho = np.arange(0, 2, 2. / num_spline_points)
  drho = np.array(drho, f32)

  density_data = np.array([2.78589606e-01, 2.02694937e-01, 1.45334053e-01,
                           1.06069912e-01, 8.42517168e-02, 7.65140344e-02,
                           7.76263116e-02, 8.23214224e-02, 8.53322309e-02,
                           8.13915861e-02, 6.59095390e-02, 4.28915711e-02,
                           2.27910928e-02, 1.13713167e-02, 6.05020311e-03,
                           3.65836583e-03, 2.60587564e-03, 2.06750708e-03,
                           1.48749693e-03, 7.40019174e-04, 6.21225205e-05],
                          np.float64)

  embedding_data = np.array([1.04222211e-10, -1.04142633e+00, -1.60359806e+00,
                             -1.89287637e+00, -2.09490167e+00, -2.26456628e+00,
                             -2.40590322e+00, -2.52245359e+00, -2.61385603e+00,
                             -2.67744693e+00, -2.71053295e+00, -2.71110418e+00,
                             -2.69287013e+00, -2.68464527e+00, -2.69204083e+00,
                             -2.68976209e+00, -2.66001244e+00, -2.60122024e+00,
                             -2.51338548e+00, -2.39650817e+00, -2.25058831e+00],
                            np.float64)

  pairwise_data = np.array([6.27032242e+01, 3.49638589e+01, 1.79007014e+01,
                            8.69001383e+00, 4.51545250e+00, 2.83260884e+00,
                            1.93216616e+00, 1.06795515e+00, 3.37740836e-01,
                            1.61087890e-02, -6.20816372e-02, -6.51314297e-02,
                            -5.35210341e-02, -5.20950200e-02, -5.51709524e-02,
                            -4.89093894e-02, -3.28051688e-02, -1.13738785e-02,
                            2.33833655e-03, 4.19132033e-03, 1.68600692e-04],
                           np.float64)

  charge_fn = spline(density_data, dr[1] - dr[0])
  embedding_fn = spline(embedding_data, drho[1] - drho[0])
  pairwise_fn = spline(pairwise_data, dr[1] - dr[0])
  return charge_fn, embedding_fn, pairwise_fn


class EnergyTest(jtu.JaxTestCase):

  @parameterized.named_parameters(jtu.cases_from_list(
      {
          'testcase_name': '_dim={}_dtype={}'.format(dim, dtype.__name__),
          'spatial_dimension': dim,
          'dtype': dtype
      } for dim in SPATIAL_DIMENSION
    for dtype in POSITION_DTYPE))
  def test_simple_spring(self, spatial_dimension, dtype):
    key = random.PRNGKey(0)
    disp, _ = space.free()
    if spatial_dimension == 2:
      R = np.array([[0., 0.], [1., 1.]], dtype=dtype)
      dist = np.sqrt(2.)
    elif spatial_dimension == 3:
      R = np.array([[0., 0., 0.], [1., 1., 1.]], dtype=dtype)
      dist = np.sqrt(3.)
    bonds = np.array([[0, 1]], np.int32)
    for _ in range(STOCHASTIC_SAMPLES):
      key, l_key, a_key = random.split(key, 3)
      length = random.uniform(key, (), minval=0.1, maxval=3.0)
      alpha = random.uniform(key, (), minval=2., maxval=4.)
      E = energy.simple_spring_bond(disp, bonds, length=length, alpha=alpha)
      E_exact = dtype((dist - length) ** alpha / alpha)
      self.assertAllClose(E(R), E_exact, True)


  # pylint: disable=g-complex-comprehension
  @parameterized.named_parameters(jtu.cases_from_list(
      {
          'testcase_name': '_dim={}_alpha={}_dtype={}'.format(
            dim, alpha, dtype.__name__),
          'spatial_dimension': dim,
          'alpha': alpha,
          'dtype': dtype
      } for dim in SPATIAL_DIMENSION
    for alpha in SOFT_SPHERE_ALPHA
    for dtype in POSITION_DTYPE))
  def test_soft_sphere(self, spatial_dimension, alpha, dtype):
    key = random.PRNGKey(0)
    alpha = f32(alpha)
    for _ in range(STOCHASTIC_SAMPLES):
      key, split_sigma, split_epsilon = random.split(key, 3)
      sigma = np.array(random.uniform(
          split_sigma, (1,), minval=0.0, maxval=3.0)[0], dtype=dtype)
      epsilon = np.array(
        random.uniform(split_epsilon, (1,), minval=0.0, maxval=4.0)[0],
        dtype=dtype)
      self.assertAllClose(
          energy.soft_sphere(
            dtype(0), sigma, epsilon, alpha), epsilon / alpha, True)
      self.assertAllClose(
        energy.soft_sphere(dtype(sigma), sigma, epsilon, alpha),
        np.array(0.0, dtype=dtype), True)

      if alpha == 3.0:
        grad_energy = grad(energy.soft_sphere)
        g = grad_energy(dtype(sigma), sigma, epsilon, alpha)
        self.assertAllClose(g, np.array(0, dtype=dtype), True)

  @parameterized.named_parameters(jtu.cases_from_list(
      {
          'testcase_name': '_dim={}_dtype={}'.format(dim, dtype.__name__),
          'spatial_dimension': dim,
          'dtype': dtype
      } for dim in SPATIAL_DIMENSION for dtype in POSITION_DTYPE))
  def test_lennard_jones(self, spatial_dimension, dtype):
    key = random.PRNGKey(0)

    for _ in range(STOCHASTIC_SAMPLES):
      key, split_sigma, split_epsilon = random.split(key, 3)
      sigma = dtype(random.uniform(
          split_sigma, (1,), minval=0.5, maxval=3.0)[0])
      epsilon = dtype(random.uniform(
          split_epsilon, (1,), minval=0.0, maxval=4.0)[0])
      dr = dtype(sigma * 2 ** (1.0 / 6.0))
      self.assertAllClose(
        energy.lennard_jones(dr, sigma, epsilon),
        np.array(-epsilon, dtype=dtype), True)
      g = grad(energy.lennard_jones)(dr, sigma, epsilon)
      self.assertAllClose(g, np.array(0, dtype=dtype), True)

  @parameterized.named_parameters(jtu.cases_from_list(
      {
          'testcase_name': '_dim={}_dtype={}'.format(dim, dtype.__name__),
          'spatial_dimension': dim,
          'dtype': dtype
      } for dim in SPATIAL_DIMENSION for dtype in POSITION_DTYPE))
  def test_isotropic_cutoff(self, spatial_dimension, dtype):
    key = random.PRNGKey(0)

    for _ in range(STOCHASTIC_SAMPLES):
      key, split_rs, split_rl, split_sigma, split_epsilon = random.split(key, 5)
      sigma = f32(random.uniform(
          split_sigma, (1,), minval=0.5, maxval=3.0)[0])
      epsilon = f32(random.uniform(
          split_epsilon, (1,), minval=0.0, maxval=4.0)[0])
      r_small = random.uniform(
          split_rs, (10,), minval=0.0, maxval=2.0 * sigma, dtype=dtype)
      r_large = random.uniform(
          split_rl, (10,), minval=2.5 * sigma, maxval=3.0 * sigma, dtype=dtype)

      r_onset = f32(2.0 * sigma)
      r_cutoff = f32(2.5 * sigma)

      E = energy.multiplicative_isotropic_cutoff(
        energy.lennard_jones, r_onset, r_cutoff)

      self.assertAllClose(
        E(r_small, sigma, epsilon),
        energy.lennard_jones(r_small, sigma, epsilon), True)
      self.assertAllClose(
        E(r_large, sigma, epsilon), np.zeros_like(r_large, dtype=dtype), True)

  @parameterized.named_parameters(jtu.cases_from_list(
      {
          'testcase_name': '_dim={}_dtype={}'.format(dim, dtype.__name__),
          'spatial_dimension': dim,
          'dtype': dtype,
      } for dim in SPATIAL_DIMENSION for dtype in POSITION_DTYPE))
  def test_soft_sphere_neighbor_list_energy(self, spatial_dimension, dtype):
    key = random.PRNGKey(1)

    box_size = f32(15.0)
    displacement, _ = space.periodic(box_size)
    exact_energy_fn = energy.soft_sphere_pair(displacement)

    R = box_size * random.uniform(
      key, (PARTICLE_COUNT, spatial_dimension), dtype=dtype)
    neighbor_fn, energy_fn = energy.soft_sphere_neighbor_list(
      displacement, box_size, R)

    idx = neighbor_fn(R)

    self.assertAllClose(
      np.array(exact_energy_fn(R), dtype=dtype),
      energy_fn(R, idx), True)

  @parameterized.named_parameters(jtu.cases_from_list(
      {
          'testcase_name': '_dim={}_dtype={}'.format(dim, dtype.__name__),
          'spatial_dimension': dim,
          'dtype': dtype,
      } for dim in SPATIAL_DIMENSION for dtype in POSITION_DTYPE))
  def test_lennard_jones_cell_neighbor_list_energy(
      self, spatial_dimension, dtype):
    key = random.PRNGKey(1)

    box_size = f32(15)
    displacement, _ = space.periodic(box_size)
    metric = space.metric(displacement)
    exact_energy_fn = energy.lennard_jones_pair(displacement)

    R = box_size * random.uniform(
      key, (PARTICLE_COUNT, spatial_dimension), dtype=dtype)
    neighbor_fn, energy_fn = energy.lennard_jones_neighbor_list(
      displacement, box_size, R)

    idx = neighbor_fn(R)
    self.assertAllClose(
      np.array(exact_energy_fn(R), dtype=dtype),
      energy_fn(R, idx), True)

  @parameterized.named_parameters(jtu.cases_from_list(
      {
          'testcase_name': '_dim={}_dtype={}'.format(dim, dtype.__name__),
          'spatial_dimension': dim,
          'dtype': dtype,
      } for dim in SPATIAL_DIMENSION for dtype in POSITION_DTYPE))
  def test_lennard_jones_neighbor_list_force(self, spatial_dimension, dtype):
    key = random.PRNGKey(1)

    box_size = f32(15.0)
    displacement, _ = space.periodic(box_size)
    metric = space.metric(displacement)
    exact_force_fn = quantity.force(energy.lennard_jones_pair(displacement))

    r = box_size * random.uniform(
      key, (PARTICLE_COUNT, spatial_dimension), dtype=dtype)
    neighbor_fn, energy_fn = energy.lennard_jones_neighbor_list(
      displacement, box_size, r)
    force_fn = quantity.force(energy_fn)

    idx = neighbor_fn(r)
    self.assertAllClose(
      np.array(exact_force_fn(r), dtype=dtype),
      force_fn(r, neighbor_idx=idx), True)

  @parameterized.named_parameters(jtu.cases_from_list(
      {
          'testcase_name': '_num_reps={}_dtype={}'.format(
            num_repetitions, dtype.__name__),
          'num_repetitions': num_repetitions,
          'dtype': dtype,
      } for num_repetitions in UNIT_CELL_SIZE for dtype in POSITION_DTYPE))
  def test_eam(self, num_repetitions, dtype):
    latvec = np.array(
        [[0, 1, 1], [1, 0, 1], [1, 1, 0]], dtype=dtype) * f32(4.05 / 2)
    atoms = np.array([[0, 0, 0]], dtype=dtype)
    atoms_repeated, latvec_repeated = lattice_repeater(
        atoms, latvec, num_repetitions)
    inv_latvec = np.array(onp.linalg.inv(onp.array(latvec_repeated)), dtype=dtype)
    displacement, _ = space.periodic_general(latvec_repeated)
    charge_fn, embedding_fn, pairwise_fn = make_eam_test_splines()
    assert charge_fn(np.array(1.0, dtype)).dtype == dtype
    assert embedding_fn(np.array(1.0, dtype)).dtype == dtype
    assert pairwise_fn(np.array(1.0, dtype)).dtype == dtype
    eam_energy = energy.eam(displacement, charge_fn, embedding_fn, pairwise_fn)
    tol = 1e-5 if dtype == np.float32 else 1e-6
    self.assertAllClose(
        eam_energy(
            np.dot(atoms_repeated, inv_latvec)) / np.array(num_repetitions ** 3, dtype),
        dtype(-3.363338), True, tol, tol)

if __name__ == '__main__':
  absltest.main()

