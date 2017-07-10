import scipy as sp
import scipy.ndimage as spim
import scipy.spatial as sptl
from skimage.morphology import disk, ball, square, cube


def snow(im, r_max=4, sigma=0.4):
    r"""
    This function extracts the true local maximum of the distance transform of
    a pore space image.  These local maxima can then be used as markers in a
    marker-based watershed segmentation such as that included in Scikit-Image
    or through the MorphoJ plugin in ImageJ.

    The SNOW network extraction algorithm (Sub-Network of an Over-segmented
    Watershed) was designed to handle to perculiarities of high porosity
    materials, but it applies equally well to other materials as well.

    Parameters
    ----------
    im : array_like
        Can be either (a) a boolean image of the domain, with ``True``
        indicating the pore space and ``False`` elsewhere, or (b) a distance
        transform of the domain calculated externally by the user.  Option (b)
        is faster if a distance transform is already available.

    r_max : scalar
        The radius of there spherical structuring element to use in the Maximum
        filter stage that is used to find peaks.  The default is 4

    sigma : scalar
        The standard deviation of the Gaussian filter used in step 1.  The
        default is 0.4.  If 0 is given then the filter is not applied, which is
        useful if a distance transform is supplied as the ``im`` argument that
        has already been processed.

    Returns
    -------
    An array the same shape as the input image, with non-zero values indicating
    the subset of peaks found by the algorithm.  The peaks are returned as a
    label array that can be directly used as markers in a watershed
    segmentation.

    """
    im = im.squeeze()
    print('_'*60)
    print("Beginning SNOW Algorithm to remove spurious peaks")

    if im.dtype == 'bool':
        dt = spim.distance_transform_edt(input=im)
    else:
        dt = im
        im = dt > 0

    if sigma > 0:
        dt = spim.gaussian_filter(input=dt, sigma=sigma)

    peaks = find_peaks(dt=dt)
    print('Initial number of peaks: ', spim.label(peaks)[1])
    peaks = trim_saddle_points(peaks=peaks, dt=dt)
    peaks = trim_nearby_peaks(peaks=peaks, dt=dt)
    peaks, N = spim.label(peaks)
    print('Final number of peaks: ', N)
    return peaks


def find_peaks(dt, r=4, footprint=None):
    r"""
    Returns all local maxima in the distance transform

    Parameters
    ----------
    dt : ND-array
        The distance transform of the pore space.  This may be calculated and
        filtered using any means desired.

    r : scalar
        The size of the structuring element used in the maximum filter.  This
        controls the localness of any maxima. The default is 3 voxels.

    footprint : ND-array
        Specifies the shape of the structuring element used to define the
        neighborhood when looking for peaks.  If none is specified then a
        spherical shape is used (or circular in 2D).

    Returns
    -------
    An ND-array of booleans with ``True`` values at the location of any local
    maxima.

    Notes
    -----
    It is also possible ot the ``peak_local_max`` function from the
    ``skimage.feature`` module as follows:

    ``peaks = peak_local_max(image=dt, min_distance=r, exclude_border=0, indices=False)``

    This automatically uses a square structuring element which is significantly
    faster than using a circular or spherical element.
    """
    dt = dt.squeeze()
    im = dt > 0
    if footprint is None:
        if im.ndim == 2:
            footprint = disk
        elif im.ndim == 3:
            footprint = ball
        else:
            raise Exception("only 2-d and 3-d images are supported")
    mx = spim.maximum_filter(dt + 2*(~im), footprint=footprint(r))
    peaks = (dt == mx)*im
    return peaks


def reduce_peaks_to_points(peaks):
    markers, N = spim.label(input=peaks, structure=cube(3))
    inds = spim.measurements.center_of_mass(input=peaks,
                                            labels=markers,
                                            index=range(1, N))
    inds = sp.floor(inds).astype(int)
    # Centroid may not be on old pixel, so create a new peaks image
    peaks = sp.zeros_like(peaks, dtype=bool)
    peaks[tuple(inds.T)] = True
    return peaks


def trim_saddle_points(peaks, dt, max_iters=10):
    r"""
    Removes peaks that were mistakenly identified because they lied on a
    saddle or ridge in the distance transform that was not actually a true
    local peak.

    Parameters
    ----------
    peaks : ND-array


    dt : ND-array


    max_iters : int


    Returns
    -------
    An image with fewer peaks than was received.
    """
    if dt.ndim == 2:
        from skimage.morphology import square as cube
    else:
        from skimage.morphology import cube
    labels, N = spim.label(peaks)
    slices = spim.find_objects(labels)
    for i in range(N):
        s = extend_slice(s=slices[i], shape=peaks.shape, pad=10)
        peaks_i = labels[s] == i+1
        dt_i = dt[s]
        im_i = dt_i > 0
        iters = 0
        peaks_dil = sp.copy(peaks_i)
        while iters < max_iters:
            iters += 1
            peaks_dil = spim.binary_dilation(input=peaks_dil,
                                             structure=cube(3))
            peaks_max = peaks_dil*sp.amax(dt_i*peaks_dil)
            peaks_extended = (peaks_max == dt_i)*im_i
            if sp.all(peaks_extended == peaks_i):
                break  # Found a true peak
            elif sp.sum(peaks_extended*peaks_i) == 0:
                peaks_i = False
                break  # Found a saddle point
        peaks[s] = peaks_i
    return peaks


def trim_nearby_peaks(peaks, dt):
    r"""
    Removes peaks that are nearer to another peak than t
    """
    if dt.ndim == 2:
        from skimage.morphology import square as cube
    else:
        from skimage.morphology import cube
    peaks, N = spim.label(peaks, structure=cube(3))
    crds = spim.measurements.center_of_mass(peaks, labels=peaks,
                                            index=sp.arange(1, N+1))
    crds = sp.vstack(crds).astype(int)  # Convert to numpy array of ints
    # Get distance between each peak as a distance map
    tree = sptl.cKDTree(data=crds)
    temp = tree.query(x=crds, k=2)
    nearest_neighbor = temp[1][:, 1]
    dist_to_neighbor = temp[0][:, 1]
    del temp, tree  # Free-up memory
    dist_to_solid = dt[list(crds.T)]  # Get distance to solid for each peak
    hits = sp.where(dist_to_neighbor < dist_to_solid)[0]
    # Drop peak that is closer to the solid than it's neighbor
    drop_peaks = []
    for peak in hits:
        if dist_to_solid[peak] < dist_to_solid[nearest_neighbor[peak]]:
            drop_peaks.append(peak)
        else:
            drop_peaks.append(nearest_neighbor[peak])
    drop_peaks = sp.unique(drop_peaks)
    # Remove peaks from image
    slices = spim.find_objects(input=peaks)
    for s in drop_peaks:
        peaks[slices[s]] = 0
    return (peaks > 0)


def trim_nearby_peaks_orig(peaks, dt, min_spacing=None):
    if min_spacing is None:
        min_spacing = dt.max()*0.8
    iters = 0
    while iters < 10:
        iters += 1
        crds = sp.where(peaks)  # Find locations of all peaks
        dist_to_solid = dt[crds]  # Get distance to solid for each peak
        dist_to_solid += sp.rand(dist_to_solid.size)*1e-5  # Perturb distances
        crds = sp.vstack(crds).T  # Convert peak locations to ND-array
        dist = sptl.distance.cdist(XA=crds, XB=crds)  # Get distance between peaks
        sp.fill_diagonal(a=dist, val=sp.inf)  # Remove 0's in diagonal
        dist[dist > min_spacing] = sp.inf  # Keep peaks that are far apart
        dist_to_nearest_neighbor = sp.amin(dist, axis=0)
        nearby_neighbors = sp.where(dist_to_nearest_neighbor < dist_to_solid)[0]
        for peak in nearby_neighbors:
            nearest_neighbor = sp.amin(sp.where(dist[peak, :] == sp.amin(dist[peak, :]))[0])
            if dist_to_solid[peak] < dist_to_solid[nearest_neighbor]:
                peaks[tuple(crds[peak])] = 0
            else:
                peaks[tuple(crds[nearest_neighbor])] = 0
        if len(nearby_neighbors) == 0:
            break
    return peaks
