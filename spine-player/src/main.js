import { AnimationState } from "@node-spine-runtimes/core-3.8.99/dist/AnimationState.js";
import { AnimationStateData } from "@node-spine-runtimes/core-3.8.99/dist/AnimationStateData.js";
import { AtlasAttachmentLoader } from "@node-spine-runtimes/core-3.8.99/dist/AtlasAttachmentLoader.js";
import { RegionAttachment } from "@node-spine-runtimes/core-3.8.99/dist/attachments/RegionAttachment.js";
import { MeshAttachment } from "@node-spine-runtimes/core-3.8.99/dist/attachments/MeshAttachment.js";
import { Skeleton } from "@node-spine-runtimes/core-3.8.99/dist/Skeleton.js";
import { SkeletonBinary } from "@node-spine-runtimes/core-3.8.99/dist/SkeletonBinary.js";
import { SkeletonJson } from "@node-spine-runtimes/core-3.8.99/dist/SkeletonJson.js";
import { TextureAtlas, TextureAtlasRegion } from "@node-spine-runtimes/core-3.8.99/dist/TextureAtlas.js";
import { Texture } from "@node-spine-runtimes/core-3.8.99/dist/Texture.js";
import { Vector2 } from "@node-spine-runtimes/core-3.8.99/dist/Utils.js";
import "./style.css";

const spine = {
  AnimationState,
  AnimationStateData,
  AtlasAttachmentLoader,
  RegionAttachment,
  MeshAttachment,
  Skeleton,
  SkeletonBinary,
  SkeletonJson,
  Texture,
  TextureAtlas,
  Vector2,
};

const elements = {
  runtimeStatus: document.querySelector("#runtime-status"),
  animationSearch: document.querySelector("#animation-search"),
  animationList: document.querySelector("#animation-list"),
  animationCount: document.querySelector("#animation-count"),
  actionSelect: document.querySelector("#action-select"),
  playButton: document.querySelector("#play-button"),
  resetButton: document.querySelector("#reset-button"),
  timeRange: document.querySelector("#time-range"),
  timeValue: document.querySelector("#time-value"),
  durationValue: document.querySelector("#duration-value"),
  speedRange: document.querySelector("#speed-range"),
  speedValue: document.querySelector("#speed-value"),
  scaleRange: document.querySelector("#scale-range"),
  scaleValue: document.querySelector("#scale-value"),
  loopToggle: document.querySelector("#loop-toggle"),
  assetSummary: document.querySelector("#asset-summary"),
  errorMessage: document.querySelector("#error-message"),
  bundleLabel: document.querySelector("#bundle-label"),
  fpsLabel: document.querySelector("#fps-label"),
  durationLabel: document.querySelector("#duration-label"),
  canvas: document.querySelector("#stage"),
  stageEmpty: document.querySelector("#stage-empty"),
};

const state = {
  manifest: null,
  bundles: [],
  currentBundleIndex: -1,
  skeleton: null,
  animationState: null,
  currentAnimations: [],
  animationName: "",
  animationData: null,
  trackEntry: null,
  duration: 0,
  playing: true,
  speed: 1,
  scale: 1,
  lastTime: performance.now(),
  frameCount: 0,
  fpsTime: performance.now(),
  imageCache: new Map(),
};

const gl = elements.canvas.getContext("webgl", {
  alpha: true,
  antialias: true,
  premultipliedAlpha: false,
});
const textureCache = new WeakMap();

function compileShader(type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(`WebGL shader error: ${gl.getShaderInfoLog(shader)}`);
  }
  return shader;
}

function createRenderer() {
  if (!gl) throw new Error("WebGL is required to render Spine mesh attachments");
  const vertexShader = compileShader(gl.VERTEX_SHADER, `
    attribute vec2 a_position;
    attribute vec2 a_texCoord;
    varying vec2 v_texCoord;
    void main() {
      v_texCoord = a_texCoord;
      gl_Position = vec4(a_position, 0.0, 1.0);
    }
  `);
  const fragmentShader = compileShader(gl.FRAGMENT_SHADER, `
    precision mediump float;
    uniform sampler2D u_texture;
    uniform vec4 u_color;
    varying vec2 v_texCoord;
    void main() {
      gl_FragColor = texture2D(u_texture, v_texCoord) * u_color;
    }
  `);
  const program = gl.createProgram();
  gl.attachShader(program, vertexShader);
  gl.attachShader(program, fragmentShader);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(`WebGL program error: ${gl.getProgramInfoLog(program)}`);
  }
  return {
    program,
    vertexBuffer: gl.createBuffer(),
    indexBuffer: gl.createBuffer(),
    positionLocation: gl.getAttribLocation(program, "a_position"),
    textureLocation: gl.getAttribLocation(program, "a_texCoord"),
    colorLocation: gl.getUniformLocation(program, "u_color"),
    samplerLocation: gl.getUniformLocation(program, "u_texture"),
  };
}

const renderer = gl ? createRenderer() : null;

class BrowserTexture extends spine.Texture {
  constructor(image, valid = true) {
    super(image);
    this.valid = valid;
  }
  setFilters() {}
  setWraps() {}
  dispose() {}
}

function placeholderRegion(path) {
  const region = new TextureAtlasRegion();
  const canvas = document.createElement("canvas");
  canvas.width = 1;
  canvas.height = 1;
  region.name = path;
  region.width = 1;
  region.height = 1;
  region.originalWidth = 1;
  region.originalHeight = 1;
  region.offsetX = 0;
  region.offsetY = 0;
  region.u = 0;
  region.v = 0;
  region.u2 = 1;
  region.v2 = 1;
  region.rotate = false;
  region.degrees = 0;
  region.texture = new BrowserTexture(canvas, false);
  return region;
}

class PermissiveAtlasAttachmentLoader extends spine.AtlasAttachmentLoader {
  constructor(atlas, missingTextures) {
    super(atlas);
    this.missingTextures = missingTextures;
  }

  findRegion(path) {
    const region = this.atlas.findRegion(path);
    if (region) return region;
    this.missingTextures.add(path);
    return placeholderRegion(path);
  }

  newRegionAttachment(skin, name, path) {
    const region = this.findRegion(path);
    region.renderObject = region;
    const attachment = new RegionAttachment(name, path);
    attachment.setRegion(region);
    return attachment;
  }

  newMeshAttachment(skin, name, path) {
    const region = this.findRegion(path);
    region.renderObject = region;
    const attachment = new MeshAttachment(name);
    attachment.region = region;
    return attachment;
  }
}

function setStatus(text, statusClass) {
  elements.runtimeStatus.textContent = text;
  elements.runtimeStatus.className = `status-chip ${statusClass}`;
}

function showError(error) {
  const message = error instanceof Error ? error.message : String(error);
  elements.errorMessage.textContent = message;
  setStatus("Runtime error", "status-error");
  elements.stageEmpty.textContent = "Unable to load resource";
  elements.stageEmpty.hidden = false;
  console.error(error);
}

function clearError() {
  elements.errorMessage.textContent = "";
}

function assetUrl(path) {
  return `/${path.split("/").map(encodeURIComponent).join("/")}`;
}

async function loadBytes(path) {
  const response = await fetch(assetUrl(path));
  if (!response.ok) throw new Error(`Failed to load ${path} (${response.status})`);
  return response.arrayBuffer();
}

function loadImage(path) {
  if (state.imageCache.has(path)) return state.imageCache.get(path);
  const image = new Image();
  const promise = new Promise((resolve, reject) => {
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`Failed to load texture ${path}`));
  });
  image.src = assetUrl(path);
  state.imageCache.set(path, promise);
  return promise;
}

function parseAtlas(atlasText, imagesByName, missingTextures) {
  const textureLoader = (path) => {
    const image = imagesByName.get(path) ?? imagesByName.get(path.split("/").pop());
    if (!image) {
      missingTextures.add(path);
      return new BrowserTexture(document.createElement("canvas"), false);
    }
    return new BrowserTexture(image, true);
  };
  return new spine.TextureAtlas(atlasText, textureLoader);
}

function selectSkeletonFile(bundle) {
  return bundle.skeleton_files.find((file) => file.endsWith(".skel"))
    ?? bundle.skeleton_files.find((file) => file.endsWith(".json"))
    ?? bundle.skeleton_files[0];
}

function selectAtlasFile(bundle) {
  return bundle.atlas_files[0];
}

function bundlePath(bundle, relativePath) {
  return `${bundle.relative_directory}/${relativePath}`;
}

function readSkeletonData(
  atlasText,
  skeletonBytes,
  skeletonPath,
  imagesByName,
  missingTextures,
  permissive = false,
) {
  const atlas = parseAtlas(atlasText, imagesByName, missingTextures);
  const attachmentLoader = permissive
    ? new PermissiveAtlasAttachmentLoader(atlas, missingTextures)
    : new spine.AtlasAttachmentLoader(atlas);
  if (skeletonPath.endsWith(".json")) {
    const skeletonJson = new spine.SkeletonJson(attachmentLoader);
    return skeletonJson.readSkeletonData(JSON.parse(new TextDecoder().decode(skeletonBytes)));
  }
  const skeletonBinary = new spine.SkeletonBinary(attachmentLoader);
  skeletonBinary.scale = 1;
  return skeletonBinary.readSkeletonData(new Uint8Array(skeletonBytes));
}

async function loadBundle(index, requestedAnimation = "") {
  clearError();
  const bundle = state.bundles[index];
  if (!bundle) return;
  elements.actionSelect.disabled = true;
  elements.playButton.disabled = true;
  elements.resetButton.disabled = true;
  elements.timeRange.disabled = true;
  elements.stageEmpty.hidden = false;
  elements.stageEmpty.textContent = "Parsing skeleton";

  try {
    const atlasPath = bundlePath(bundle, selectAtlasFile(bundle));
    const skeletonPath = bundlePath(bundle, selectSkeletonFile(bundle));
    const atlasText = await (await fetch(assetUrl(atlasPath))).text();
    const imagePaths = bundle.image_files.map((file) => bundlePath(bundle, file));
    const loadedImages = await Promise.all(imagePaths.map(async (path) => {
      try {
        return [path, await loadImage(path), null];
      } catch (error) {
        return [path, null, error];
      }
    }));
    const imagesByName = new Map();
    const missingTextures = new Set();
    for (const [path, image, error] of loadedImages) {
      if (error) {
        missingTextures.add(path);
        continue;
      }
      imagesByName.set(path, image);
      imagesByName.set(path.split("/").pop(), image);
    }
    const skeletonBytes = await loadBytes(skeletonPath);
    const skeletonData = readSkeletonData(
      atlasText,
      skeletonBytes,
      skeletonPath,
      imagesByName,
      missingTextures,
      true,
    );
    const missingTextureNames = new Set([...missingTextures].map((path) => path.split("/").pop()));
    const skeleton = new spine.Skeleton(skeletonData);
    const animationStateData = new spine.AnimationStateData(skeletonData);
    const animationState = new spine.AnimationState(animationStateData);
    state.skeleton = skeleton;
    state.animationState = animationState;
    state.currentBundleIndex = index;
    state.currentAnimations = skeletonData.animations;
    const firstAnimation = requestedAnimation || (skeletonData.animations.length ? skeletonData.animations[0].name : "");
    fillCurrentActionSelect();
    updateBundleSelection();
    if (firstAnimation) setActiveAnimation(firstAnimation);
    elements.bundleLabel.textContent = `${bundle.relative_directory} / ${selectSkeletonFile(bundle)}`;
    // Keep the canvas visible when only some attachments are unavailable.
    // The detailed missing-texture warning is shown in the sidebar instead.
    elements.stageEmpty.hidden = true;
    elements.stageEmpty.textContent = "";
    elements.actionSelect.disabled = skeletonData.animations.length === 0;
    elements.playButton.disabled = false;
    elements.resetButton.disabled = false;
    elements.timeRange.disabled = skeletonData.animations.length === 0;
    elements.playButton.textContent = state.playing ? "Pause" : "Play";
    updateSummary(bundle, skeletonData);
    if (missingTextureNames.size) {
      elements.errorMessage.textContent = `Skeleton parsed, but texture data is not a browser image: ${[...missingTextureNames][0]}`;
      setStatus("Texture blocked", "status-warning");
    } else {
      setStatus("Runtime ready", "status-ready");
    }
  } catch (error) {
    state.skeleton = null;
    state.animationState = null;
    state.trackEntry = null;
    state.animationData = null;
    state.currentAnimations = [];
    state.duration = 0;
    showError(error);
  }
}

function formatTime(seconds) {
  return `${Math.max(0, seconds).toFixed(2)}s`;
}

function fillBundleList() {
  elements.animationList.replaceChildren();
  elements.animationCount.textContent = String(state.bundles.length);
  for (const [index, bundle] of state.bundles.entries()) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "animation-item";
    button.dataset.bundleIndex = String(index);
    button.setAttribute("role", "option");
    const displayName = bundle.name || bundle.relative_directory.split("/").pop();
    button.dataset.animationName = displayName.toLocaleLowerCase();
    const name = document.createElement("span");
    name.className = "animation-item-name";
    name.textContent = displayName;
    const source = document.createElement("span");
    source.className = "animation-item-source";
    source.textContent = bundle.relative_directory;
    const duration = document.createElement("span");
    duration.className = "animation-item-time";
    duration.textContent = `${bundle.image_files.length} tex`;
    button.append(name, source, duration);
    elements.animationList.append(button);
  }
  fillCurrentActionSelect();
}

function fillCurrentActionSelect() {
  elements.actionSelect.replaceChildren();
  for (const animation of state.currentAnimations) {
    const option = document.createElement("option");
    option.value = animation.name;
    option.textContent = animation.name;
    elements.actionSelect.append(option);
  }
}

function updateSummary(bundle, skeletonData) {
  const values = [
    ["Bundles", state.bundles.length],
    ["Skeleton", selectSkeletonFile(bundle)],
    ["Textures", bundle.image_files.length],
  ];
  elements.assetSummary.replaceChildren(...values.map(([label, value]) => {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    term.textContent = label;
    const detail = document.createElement("dd");
    detail.textContent = value;
    row.append(term, detail);
    return row;
  }));
}

function updateBundleSelection() {
  for (const button of elements.animationList.querySelectorAll(".animation-item")) {
    const active = Number(button.dataset.bundleIndex) === state.currentBundleIndex;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  }
  elements.actionSelect.value = state.animationName;
}

function updateTimeline() {
  const trackTime = state.trackEntry?.trackTime ?? 0;
  const visibleTime = Math.min(Math.max(trackTime, 0), state.duration);
  elements.timeRange.max = String(Math.max(state.duration, 0.001));
  elements.timeRange.value = String(visibleTime);
  elements.timeValue.textContent = formatTime(visibleTime);
  elements.durationValue.textContent = formatTime(state.duration);
  elements.durationLabel.textContent = formatTime(state.duration);
  elements.durationValue.title = state.animationName || "No animation";
}

function setActiveAnimation(name) {
  if (!state.animationState || !state.skeleton) return;
  const animation = state.skeleton.data.animations.find((item) => item.name === name);
  if (!animation) return;
  state.animationName = name;
  state.animationData = animation;
  state.duration = animation.duration;
  state.skeleton.setToSetupPose();
  state.trackEntry = state.animationState.setAnimation(0, name, elements.loopToggle.checked);
  updateBundleSelection();
  updateTimeline();
}

function applyCurrentPose() {
  if (!state.animationState || !state.skeleton) return;
  state.animationState.apply(state.skeleton);
  state.skeleton.updateWorldTransform();
  drawSkeleton();
  updateTimeline();
}

function resizeCanvas() {
  const rect = elements.canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.floor(rect.width * ratio));
  const height = Math.max(1, Math.floor(rect.height * ratio));
  if (elements.canvas.width !== width || elements.canvas.height !== height) {
    elements.canvas.width = width;
    elements.canvas.height = height;
  }
}

function getWebGLTexture(image) {
  if (textureCache.has(image)) return textureCache.get(image);
  const texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, texture);
  // Spine atlas UVs use the HTML image's top-left orientation already.
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
  textureCache.set(image, texture);
  return texture;
}

function drawSkeleton() {
  resizeCanvas();
  if (!renderer) return;
  gl.viewport(0, 0, elements.canvas.width, elements.canvas.height);
  gl.clearColor(0, 0, 0, 0);
  gl.clear(gl.COLOR_BUFFER_BIT);
  if (!state.skeleton) return;

  const boundsOffset = new spine.Vector2();
  const boundsSize = new spine.Vector2();
  state.skeleton.getBounds(boundsOffset, boundsSize);
  const scale = Math.min(
    elements.canvas.width / Math.max(boundsSize.x, 1),
    elements.canvas.height / Math.max(boundsSize.y, 1),
  ) * 0.78 * state.scale;
  const boundsCenterX = boundsOffset.x + boundsSize.x / 2;
  const boundsCenterY = boundsOffset.y + boundsSize.y / 2;

  gl.useProgram(renderer.program);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
  gl.disable(gl.DEPTH_TEST);
  gl.disable(gl.CULL_FACE);
  gl.activeTexture(gl.TEXTURE0);
  gl.uniform1i(renderer.samplerLocation, 0);

  for (const slot of state.skeleton.drawOrder) {
    const attachment = slot.getAttachment();
    if (attachment instanceof spine.RegionAttachment) {
      const vertices = new Float32Array(8);
      attachment.computeWorldVertices(slot.bone, vertices, 0, 2);
      drawTexturedAttachment(
        slot,
        attachment,
        vertices,
        attachment.uvs,
        [0, 1, 2, 2, 3, 0],
        boundsCenterX,
        boundsCenterY,
        scale,
      );
    } else if (attachment instanceof spine.MeshAttachment) {
      const vertices = new Float32Array(attachment.worldVerticesLength);
      attachment.computeWorldVertices(slot, 0, attachment.worldVerticesLength, vertices, 0, 2);
      drawTexturedAttachment(
        slot,
        attachment,
        vertices,
        attachment.uvs,
        attachment.triangles,
        boundsCenterX,
        boundsCenterY,
        scale,
      );
    }
  }
}

function drawTexturedAttachment(
  slot,
  attachment,
  worldVertices,
  uvs,
  triangles,
  boundsCenterX,
  boundsCenterY,
  scale,
) {
  const texture = attachment.region?.texture;
  const image = texture?.getImage();
  if (!texture?.valid || !image || !image.complete || !uvs?.length || !triangles?.length) return;

  const vertexCount = worldVertices.length / 2;
  const packedVertices = new Float32Array(vertexCount * 4);
  for (let index = 0; index < vertexCount; index += 1) {
    packedVertices[index * 4] = (
      (worldVertices[index * 2] - boundsCenterX) * scale * 2
    ) / elements.canvas.width;
    packedVertices[index * 4 + 1] = (
      (worldVertices[index * 2 + 1] - boundsCenterY) * scale * 2
    ) / elements.canvas.height;
    packedVertices[index * 4 + 2] = uvs[index * 2];
    packedVertices[index * 4 + 3] = uvs[index * 2 + 1];
  }

  gl.bindBuffer(gl.ARRAY_BUFFER, renderer.vertexBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, packedVertices, gl.DYNAMIC_DRAW);
  gl.enableVertexAttribArray(renderer.positionLocation);
  gl.vertexAttribPointer(renderer.positionLocation, 2, gl.FLOAT, false, 16, 0);
  gl.enableVertexAttribArray(renderer.textureLocation);
  gl.vertexAttribPointer(renderer.textureLocation, 2, gl.FLOAT, false, 16, 8);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, renderer.indexBuffer);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(triangles), gl.DYNAMIC_DRAW);
  gl.bindTexture(gl.TEXTURE_2D, getWebGLTexture(image));

  const skeletonColor = state.skeleton.color;
  gl.uniform4f(
    renderer.colorLocation,
    skeletonColor.r * slot.color.r * attachment.color.r,
    skeletonColor.g * slot.color.g * attachment.color.g,
    skeletonColor.b * slot.color.b * attachment.color.b,
    skeletonColor.a * slot.color.a * attachment.color.a,
  );
  gl.drawElements(gl.TRIANGLES, triangles.length, gl.UNSIGNED_SHORT, 0);
}

function frame(now) {
  const delta = Math.min((now - state.lastTime) / 1000, 0.1);
  state.lastTime = now;
  if (state.skeleton && state.animationState && state.playing) {
    state.animationState.update(delta * state.speed);
    state.animationState.apply(state.skeleton);
    state.skeleton.updateWorldTransform();
    drawSkeleton();
  } else {
    drawSkeleton();
  }
  state.frameCount += 1;
  if (now - state.fpsTime > 500) {
    elements.fpsLabel.textContent = `${Math.round(state.frameCount * 1000 / (now - state.fpsTime))} FPS`;
    state.frameCount = 0;
    state.fpsTime = now;
  }
  updateTimeline();
  requestAnimationFrame(frame);
}

elements.animationList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-bundle-index]");
  if (!button) return;
  const bundleIndex = Number(button.dataset.bundleIndex);
  if (bundleIndex !== state.currentBundleIndex) {
    await loadBundle(bundleIndex);
  }
});
elements.animationSearch.addEventListener("input", () => {
  const query = elements.animationSearch.value.trim().toLowerCase();
  for (const button of elements.animationList.querySelectorAll(".animation-item")) {
    button.hidden = query.length > 0 && !button.dataset.animationName.includes(query);
  }
});
elements.actionSelect.addEventListener("change", () => {
  setActiveAnimation(elements.actionSelect.value);
});
elements.playButton.addEventListener("click", () => {
  state.playing = !state.playing;
  elements.playButton.textContent = state.playing ? "Pause" : "Play";
});
elements.resetButton.addEventListener("click", () => {
  setActiveAnimation(state.animationName);
  applyCurrentPose();
});
elements.timeRange.addEventListener("input", () => {
  if (!state.trackEntry) return;
  state.trackEntry.trackTime = Number(elements.timeRange.value);
  applyCurrentPose();
});
elements.speedRange.addEventListener("input", () => {
  state.speed = Number(elements.speedRange.value);
  elements.speedValue.textContent = `${state.speed.toFixed(2)}x`;
});
elements.scaleRange.addEventListener("input", () => {
  state.scale = Number(elements.scaleRange.value);
  elements.scaleValue.textContent = `${state.scale.toFixed(2)}x`;
});
elements.loopToggle.addEventListener("change", () => {
  if (state.animationName) setActiveAnimation(state.animationName);
});

async function bootstrap() {
  try {
    if (!renderer) throw new Error("WebGL is unavailable in this browser");
    const response = await fetch("/spine-index.json");
    if (!response.ok) throw new Error(`Spine index not found (${response.status})`);
    state.manifest = await response.json();
    state.bundles = state.manifest.bundles.filter((bundle) => bundle.atlas_files.length && bundle.skeleton_files.length && bundle.image_files.length);
    if (!state.bundles.length) throw new Error("No complete Spine bundles found in the extracted output");
    fillBundleList();
    await loadBundle(0);
  } catch (error) {
    showError(error);
  }
  requestAnimationFrame(frame);
}

bootstrap();
