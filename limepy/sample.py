# -*- coding: utf-8 -*-
from __future__ import division, absolute_import
import numpy
from numpy import exp, sqrt, pi, sin, cos
from scipy.special import gamma, gammainc, dawsn, hyp1f1, erfi
from scipy.optimize import brentq
from scipy import random
from math import factorial



class sample:
    def __init__(self, mod, np, **kwargs):
        r""""
        
        Sample positions and velocities from DF generated by LIMEPY


        Parameters:

        mod : Python object
          Model generated by LIMEPY
        np : scaler
           Number of points to be generated
        seed : scaler, optional
             Random seed 
        verbose : bool, optional
                Print diagnostics; default=False
        """
        
        self._set_params_and_init(mod, np, **kwargs)
        self._set_masses(mod)
        self._sample_r(mod)
        self._sample_v(mod)
        self._to_cartesian()

        if (self.verbose): self._summary()

    def _set_params_and_init(self, mod, np, **kwargs):
        if not mod.converged: raise ValueError(" Error: This model has not converged, abort sampling ...")
            
        self.seed = 199
        self.verbose = False
        if kwargs is not None:
            for key, value in kwargs.iteritems():
                setattr(self, key, value)

        random.seed(self.seed)  
        self.np = np
        if (mod.multi):
            #  np is recalculated in case of multi mass
            self.Nj = numpy.array(m.Mj/m.mj, dtype='int')
            self.np = sum(self.Nj)

            if min(self.Nj)==0: raise ValueError(" Error: One of the mass components has zero stars!")
        self.mod = mod
        self.ani = True if min(mod.raj)/mod.rt < 3 else False

    def _set_masses(self, mod):
        # Create mass array
        if not mod.multi:
            self.m = numpy.zeros(self.np) + mod.M/self.np
            self.ra = mod.ra

        if mod.multi:
            self.Nstart = numpy.zeros(mod.nmbin)
            self.Nend = numpy.zeros(mod.nmbin)
            for j in range(mod.nmbin):
                self.Nstart[j] = sum(self.Nj[0:j])
                self.Nend[j] = self.Nstart[j] + self.Nj[j]

            self.m = numpy.zeros(self.np)
            self.ra = numpy.zeros(self.np)
            self.sig2j = numpy.zeros(self.np)
            for j in range(mod.nmbin):
                self.m[self.Nstart[j]:self.Nend[j]] = mod.mj[j]
                self.ra[self.Nstart[j]:self.Nend[j]] = mod.raj[j]
                self.sig2j[self.Nstart[j]:self.Nend[j]] = mod.sig2j[j]
            if (self.verbose): print " N = ",self.Nj

    def _sample_r(self, m):
        if (self.verbose): print " sample r ..."
        ran = random.rand(self.np)

        if not m.multi:
            self.r = numpy.interp(ran, m.mc/m.mc[-1], m.r)

        if m.multi:
            self.r = numpy.zeros(self.np)
            for j in range(m.nmbin):
                s, e = self.Nstart[j], self.Nend[j]
                m.mcj[j][0] = 0.5*m.mcj[j][1]
                self.r[s:e] = numpy.interp(ran[s:e], m.mcj[j]/m.mcj[j][-1], m.r)

        # get dimensionless potential
        self.phihat = m.interp_phi(self.r)/m.sig2 
        return

    def _sample_v(self, m):
        # Sample random values for x = k**1.5
        self.xmax= self.phihat**1.5

        nx = 10
        self.nx = nx
        frac = numpy.linspace(0,1,nx+1)

        self.x = numpy.zeros(len(self.r))
        for j in range(1,nx):
            self.x = numpy.vstack((self.x, self.xmax*frac[j]))
        self.x = numpy.vstack((self.x, self.xmax))

        self.k, self.v, self.rfinal = [], [], []
        for j in range(self.mod.nmbin):
            if (self.verbose): print "   set-up segments for velocity cdf ..."

            self.ycum = numpy.zeros(self.np)        
            self.y = self._pdf_k32(self.r, self.phihat, self.x[0], j)
            for i in range(1,nx):
                self.y = numpy.vstack((self.y, self._pdf_k32(self.r, self.phihat, self.x[i], j)))
            self.y = numpy.vstack((self.y, 0*self.r, self.x[-1]))

            if (self.verbose): print " cdf ..."
            self._compute_cdf()

            if (self.verbose): print " sample k^3/2 points ..."
            self._sample_k(j)

        self.r = self.rfinal
        self._sample_angles(self.np)

    def _compute_cdf(self):
        for j in range(len(self.x)-1):
            dy = self.y[j]*(self.x[j+1] - self.x[j])
            self.ycum = numpy.vstack((self.ycum, self.ycum[-1]+dy))

    def _Eg(self,x,s):
        return exp(x)*gammainc(s,x) if s>0 else exp(x)

    def _pdf_k32(self, r, f, x, j):
        # PDF of k^3/2
        g = self.mod.g
        x13 = x**(1./3)
        x23 = x**(2./3)
        sig2fac = self.mod.sig2/self.mod.sig2j[j]
        E = (f-x23)*sig2fac

        c = (x>0)
        func = numpy.zeros(len(x))
        if (sum(c)>0):
            if (self.ani): 
                p = r/self.mod.raj[j]
                F = dawsn(x13*p*sqrt(sig2fac))/p
                func[c] = F[c]/(x13[c]*sqrt(sig2fac))*self._Eg(E[c],g) 
            else:
                func[c] = self._Eg(E[c],g) 
        if (sum(~c)>0): func[~c] = self._Eg(E[~c],g) 

        return func
        
    def _sample_k(self, jbin):
        # y(x) = y_j
        # cdf(x) = ycum_j + y_j*(x - x_j)
        # x = R/y_j + x_j
        np = self.np
        iter=0

        c = numpy.zeros(np, dtype='bool')+True

        if self.mod.multi:
            sta, end = self.Nstart[jbin], self.Nend[jbin]
            c[0:sta] = False
            c[end::] = False

        ycum0 = self.ycum[:,c]
        rtmp0 = self.r[c]

        ftmp0 = self.phihat[c]
        y0 = self.y[:,c]
        x0 = self.x[:,c]
        c = numpy.zeros(self.Nj[jbin], dtype='bool')+True
                    
        while (sum(c) > 0):
            nc = sum(c)

            ycum = ycum0[:,c]
            rtmp = rtmp0[c]
            ftmp = ftmp0[c]
            y = y0[:,c]
            x = x0[:,c]

            R = random.rand(nc)*ycum[-1]
            xtmp = numpy.zeros(nc)
            P = numpy.zeros(nc)

            for j in range(self.nx):
                cr = (R>=ycum[j])&(R<ycum[j+1])
                if (sum(cr)>0):
                    xtmp[cr] = (R[cr]-ycum[j,cr])/y[j,cr] + x[j,cr]
                    P[cr] = y[j,cr]

            R2 = random.rand(nc)*P
            f = self._pdf_k32(rtmp, ftmp, xtmp, jbin)

            c = (R2>f)

            if (iter==0):
                xsamp = xtmp[~c]
                r = rtmp[~c]
            else:
                xsamp = numpy.r_[xsamp, xtmp[~c]]
                r = numpy.r_[r, rtmp[~c]]

            iter+=1

        # Assign final velocities and update r because of shuffling
        self.k = numpy.r_[self.k, xsamp**(2./3)] 
        self.v = numpy.r_[self.v, sqrt(2*xsamp**(2/3)*self.mod.sig2)] 
        self.rfinal = numpy.r_[self.rfinal, r]

    def _pdf_angle(self, q, *args):
        # Sample random values for: q = cos(theta)
        # P(q) = erfi(sqrt(k)*p*q)/erfi(sqrt(k)*p)

        a, R = args
        return R  - erfi(a*q)/erfi(a)

    def _sample_angles(self,np):
        if (self.verbose): print "   sample angles ..."
        R = random.rand(np)

        if self.ani:
            # Anisotropic systems sample angles: cdf(q) = erfi(a*q)/erfi(a), a = k*p^2
            p = self.r/self.ra
            a = p*sqrt(self.k)
            if self.mod.multi:
                a *= sqrt(self.mod.sig2/self.sig2j)
            self.q = numpy.zeros(np)

            for j in range(np):
                self.q[j] = brentq(self._pdf_angle, 0, 1, args=(a[j], R[j]))
        else:
            # Isotropic: cdf(q) = q
            self.q = R

        self.vr = self.v*self.q*random.choice((-1,1),size=self.np)
        self.vt = self.v*sqrt(1-self.q**2)

    def _to_cartesian(self):
        if (self.verbose): print " convert to cartesian coordinates ..."
        r = self.r
        r2 = r**2
        R1 = random.rand(self.np)
        R2 = random.rand(self.np)
        self.x = (1-2*R1)*self.r
        self.y = sqrt(r2 - self.x**2)*cos(2*pi*R2)
        self.z = sqrt(r2 - self.x**2)*sin(2*pi*R2)
        if (self.ani):
            R1 = random.rand(self.np)
            vphi = self.vt*cos(2*pi*R1)
            vtheta = self.vt*sin(2*pi*R1)
            theta = numpy.arccos(self.z/r)
            phi = numpy.arctan2(self.y, self.x)
            
            self.vx = self.vr*sin(theta)*cos(phi) + vtheta*cos(theta)*cos(phi) - vphi*sin(phi)
            self.vy = self.vr*sin(theta)*sin(phi) + vtheta*cos(theta)*sin(phi) + vphi*cos(phi)
            self.vz = self.vr*cos(theta) - vtheta*sin(theta)
        else:
            v2 = self.v**2
            R1 = random.rand(self.np)
            R2 = random.rand(self.np)
            self.vx = (1-2*R1)*self.v
            self.vy = sqrt(v2 - self.vx**2)*cos(2*pi*R2)
            self.vz = sqrt(v2 - self.vx**2)*sin(2*pi*R2)

    def _summary(self):
        print " done! "
        m = self.mod
        f = -self.phihat*m.sig2 - m.G*m.M/m.rt 

        print "       U: sample = %12.4e; model = %12.4e"%(0.5*sum(self.m*f), m.U)
        print "       K: sample = %12.4e; model = %12.4e"%(sum(0.5*self.m*self.v**2), m.K)
        print "       Q: sample = %12.4e; model = %12.4e"%(sum(0.5*self.m*self.v**2)/(0.5*sum(self.m*f)), m.K/m.U)
        print "  2Kr/Kt: sample = %12.4f; model = %12.4f"%(2*sum(self.vr**2)/sum(self.vt**2),2*m.Kr/m.Kt)

        if m.multi:
            
            print "\n  Components: "
            for j in range(m.nmbin):
                c=(self.m==m.mj[j])
                print "      Kj: sample = %12.4e; model = %12.4e"%(sum(0.5*self.m[c]*self.v[c]**2), m.Kj[j])

            for j in range(m.nmbin):
                c=(self.m==m.mj[j])
                print " 2Kr/Ktj: sample = %12.4e; model = %12.4e"%(2*sum(self.vr[c]**2)/sum(self.vt[c]**2),2*m.Krj[j]/m.Ktj[j])