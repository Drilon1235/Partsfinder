// Partsfinder - small WebGL viewer for STL meshes (no libraries).
// Drag = rotate, Shift+drag or right-drag = pan, wheel = zoom, double-click = reset view.
'use strict';

(function () {
  // ---- STL parsing (binary and ASCII) ------------------------------------------------------
  function parseSTL(buffer) {
    const bytes = new Uint8Array(buffer);
    const dv = new DataView(buffer);
    const n = bytes.length >= 84 ? dv.getUint32(80, true) : 0;
    if (n > 0 && 84 + n * 50 === bytes.length) {
      const pos = new Float32Array(n * 9);
      for (let i = 0; i < n; i++) {
        const o = 84 + i * 50 + 12;
        for (let k = 0; k < 9; k++) pos[i * 9 + k] = dv.getFloat32(o + k * 4, true);
      }
      return pos;
    }
    const text = new TextDecoder().decode(bytes);
    const nums = [];
    const re = /vertex\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)/g;
    let m;
    while ((m = re.exec(text))) nums.push(+m[1], +m[2], +m[3]);
    if (!nums.length) throw new Error('The model file contains no triangles.');
    return new Float32Array(nums);
  }

  function faceNormals(pos) {
    const nrm = new Float32Array(pos.length);
    for (let i = 0; i < pos.length; i += 9) {
      const ux = pos[i + 3] - pos[i], uy = pos[i + 4] - pos[i + 1], uz = pos[i + 5] - pos[i + 2];
      const wx = pos[i + 6] - pos[i], wy = pos[i + 7] - pos[i + 1], wz = pos[i + 8] - pos[i + 2];
      let nx = uy * wz - uz * wy, ny = uz * wx - ux * wz, nz = ux * wy - uy * wx;
      const l = Math.hypot(nx, ny, nz) || 1;
      nx /= l; ny /= l; nz /= l;
      for (let k = 0; k < 3; k++) { nrm[i + k * 3] = nx; nrm[i + k * 3 + 1] = ny; nrm[i + k * 3 + 2] = nz; }
    }
    return nrm;
  }

  // ---- matrices (column-major, as WebGL expects) ----------------------------------------
  function perspective(fovy, aspect, near, far) {
    const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
    return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0]);
  }
  function lookAt(eye, target, up) {
    let zx = eye[0] - target[0], zy = eye[1] - target[1], zz = eye[2] - target[2];
    let l = Math.hypot(zx, zy, zz) || 1; zx /= l; zy /= l; zz /= l;
    let xx = up[1] * zz - up[2] * zy, xy = up[2] * zx - up[0] * zz, xz = up[0] * zy - up[1] * zx;
    l = Math.hypot(xx, xy, xz) || 1; xx /= l; xy /= l; xz /= l;
    const yx = zy * xz - zz * xy, yy = zz * xx - zx * xz, yz = zx * xy - zy * xx;
    return new Float32Array([
      xx, yx, zx, 0, xy, yy, zy, 0, xz, yz, zz, 0,
      -(xx * eye[0] + xy * eye[1] + xz * eye[2]),
      -(yx * eye[0] + yy * eye[1] + yz * eye[2]),
      -(zx * eye[0] + zy * eye[1] + zz * eye[2]), 1]);
  }

  const VS = `
    attribute vec3 aPos; attribute vec3 aNrm;
    uniform mat4 uView; uniform mat4 uProj; varying vec3 vNrm; varying vec3 vPos;
    void main() { vNrm = aNrm; vPos = aPos; gl_Position = uProj * uView * vec4(aPos, 1.0); }`;
  const FS = `
    precision mediump float; varying vec3 vNrm; varying vec3 vPos;
    uniform vec3 uEye; uniform vec3 uKey; uniform vec3 uFill; uniform vec3 uColor;
    void main() {
      vec3 n = normalize(vNrm);
      vec3 v = normalize(uEye - vPos);
      if (dot(n, v) < 0.0) n = -n;                      // show inside faces too (open meshes)
      float key = max(dot(n, normalize(uKey)), 0.0);
      float fill = max(dot(n, normalize(uFill)), 0.0);
      vec3 h = normalize(normalize(uKey) + v);
      float spec = pow(max(dot(n, h), 0.0), 40.0) * 0.25;
      vec3 c = uColor * (0.32 + 0.58 * key + 0.22 * fill) + vec3(spec);
      gl_FragColor = vec4(c, 1.0);
    }`;

  function shader(gl, type, src) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) || 'shader error');
    return s;
  }

  // ---- viewer -------------------------------------------------------------------------------
  function createViewer(canvas, buffer) {
    const gl = canvas.getContext('webgl', { antialias: true, preserveDrawingBuffer: false });
    if (!gl) throw new Error('3D is not supported on this computer (no WebGL).');
    const pos = parseSTL(buffer);
    const nrm = faceNormals(pos);

    // centre and size of the model
    let min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < pos.length; i += 3) {
      for (let k = 0; k < 3; k++) { if (pos[i + k] < min[k]) min[k] = pos[i + k]; if (pos[i + k] > max[k]) max[k] = pos[i + k]; }
    }
    const centre = [0, 1, 2].map((k) => (min[k] + max[k]) / 2);
    const radius = Math.max(1e-6, Math.hypot(max[0] - min[0], max[1] - min[1], max[2] - min[2]) / 2);

    const prog = gl.createProgram();
    gl.attachShader(prog, shader(gl, gl.VERTEX_SHADER, VS));
    gl.attachShader(prog, shader(gl, gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error('3D could not start.');
    gl.useProgram(prog);
    const attr = (name, data) => {
      const b = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      const loc = gl.getAttribLocation(prog, name);
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, 3, gl.FLOAT, false, 0, 0);
    };
    attr('aPos', pos);
    attr('aNrm', nrm);
    const u = (n) => gl.getUniformLocation(prog, n);
    gl.enable(gl.DEPTH_TEST);

    // camera: orbit around the centre; CAD convention Z up
    const start = { yaw: -0.8, pitch: 0.55, dist: radius * 2.8, pan: [0, 0, 0] };
    let cam = { ...start, pan: [0, 0, 0] };
    let raf = 0;

    function eyeAndTarget() {
      const t = [centre[0] + cam.pan[0], centre[1] + cam.pan[1], centre[2] + cam.pan[2]];
      const cp = Math.cos(cam.pitch);
      return { eye: [t[0] + cam.dist * cp * Math.cos(cam.yaw), t[1] + cam.dist * cp * Math.sin(cam.yaw), t[2] + cam.dist * Math.sin(cam.pitch)], t };
    }

    function draw() {
      raf = 0;
      const dpr = window.devicePixelRatio || 1;
      const w = Math.max(1, Math.round(canvas.clientWidth * dpr)), h = Math.max(1, Math.round(canvas.clientHeight * dpr));
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      gl.viewport(0, 0, w, h);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      const { eye, t } = eyeAndTarget();
      gl.uniformMatrix4fv(u('uProj'), false, perspective(0.6, w / h, cam.dist / 100, cam.dist + radius * 4));
      gl.uniformMatrix4fv(u('uView'), false, lookAt(eye, t, [0, 0, 1]));
      gl.uniform3fv(u('uEye'), eye);
      // lights follow the camera: key from top-left-front, fill from the other side
      gl.uniform3fv(u('uKey'), [eye[0] - t[0] + radius, eye[1] - t[1] - radius, eye[2] - t[2] + radius * 2]);
      gl.uniform3fv(u('uFill'), [-(eye[0] - t[0]), -(eye[1] - t[1]), radius]);
      gl.uniform3fv(u('uColor'), [0.40, 0.56, 0.84]);    // the same blue as the previews
      gl.drawArrays(gl.TRIANGLES, 0, pos.length / 3);
    }
    const redraw = () => { if (!raf) raf = requestAnimationFrame(draw); };

    // ---- interaction ----
    let drag = null;
    const onDown = (e) => {
      drag = { x: e.clientX, y: e.clientY, pan: e.button === 2 || e.shiftKey };
      canvas.setPointerCapture(e.pointerId);
    };
    const onMove = (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      drag.x = e.clientX; drag.y = e.clientY;
      if (drag.pan) {
        const s = cam.dist / canvas.clientHeight * 1.1;
        const rx = -Math.sin(cam.yaw), ry = Math.cos(cam.yaw);               // camera right
        const up = [-Math.sin(cam.pitch) * Math.cos(cam.yaw), -Math.sin(cam.pitch) * Math.sin(cam.yaw), Math.cos(cam.pitch)];
        cam.pan[0] += (-dx * rx + dy * up[0]) * s;
        cam.pan[1] += (-dx * ry + dy * up[1]) * s;
        cam.pan[2] += dy * up[2] * s;
      } else {
        cam.yaw -= dx * 0.008;
        cam.pitch = Math.max(-1.5, Math.min(1.5, cam.pitch + dy * 0.008));
      }
      redraw();
    };
    const onUp = () => { drag = null; };
    const onWheel = (e) => {
      e.preventDefault();
      cam.dist = Math.max(radius * 0.3, Math.min(radius * 20, cam.dist * Math.exp(e.deltaY * 0.0012)));
      redraw();
    };
    const reset = () => { cam = { ...start, pan: [0, 0, 0] }; redraw(); };
    const noMenu = (e) => e.preventDefault();
    canvas.addEventListener('pointerdown', onDown);
    canvas.addEventListener('pointermove', onMove);
    canvas.addEventListener('pointerup', onUp);
    canvas.addEventListener('pointercancel', onUp);
    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('dblclick', reset);
    canvas.addEventListener('contextmenu', noMenu);
    const ro = new ResizeObserver(redraw);
    ro.observe(canvas);
    redraw();

    return {
      triangles: pos.length / 9,
      size: [0, 1, 2].map((k) => max[k] - min[k]),
      reset,
      destroy() {
        ro.disconnect();
        if (raf) cancelAnimationFrame(raf);
        const lose = gl.getExtension('WEBGL_lose_context');
        if (lose) lose.loseContext();
      },
    };
  }

  window.PartsViewer = { createViewer, parseSTL };
})();
