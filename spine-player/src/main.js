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
  previousAnimation: document.querySelector("#previous-animation"),
  nextAnimation: document.querySelector("#next-animation"),
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
const animationListContent = document.createElement("div");
animationListContent.className = "animation-list-content";
elements.animationList.append(animationListContent);

const ANIMATION_ROW_HEIGHT = 46;
const ANIMATION_LIST_OVERSCAN = 6;

const state = {
  manifest: null,
  bundles: [],
  bundleEntries: [],
  filteredBundleEntries: [],
  currentBundleIndex: -1,
  layers: [],
  skeleton: null,
  animationState: null,
  currentAnimations: [],
  animationName: "",
  animationData: null,
  trackEntry: null,
  duration: 0,
  viewBounds: null,
  playing: true,
  speed: 1,
  scale: 1,
  lastTime: performance.now(),
  frameCount: 0,
  fpsTime: performance.now(),
  imageCache: new Map(),
  listRenderFrame: 0,
  listFilterFrame: 0,
};

const gl = elements.canvas.getContext("webgl", {
  alpha: true,
  antialias: true,
  premultipliedAlpha: true,
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

function bundleIsComplete(bundle) {
  return bundle.atlas_files.length && bundle.skeleton_files.length && bundle.image_files.length;
}

function buildPlayerEntries(manifest) {
  const bundles = manifest.bundles.filter(bundleIsComplete);
  const bundleById = new Map(bundles.map((bundle) => [bundle.id, bundle]));
  const usedBundleIds = new Set();
  const scenes = [];
  for (const scene of manifest.scenes ?? []) {
    const layers = scene.layers.flatMap((layer) => {
      const bundle = bundleById.get(layer.bundle_id);
      return bundle ? [{ role: layer.role, bundle }] : [];
    });
    if (layers.length !== scene.layers.length || layers.length < 2) continue;
    const primaryLayerIndex = Math.max(
      0,
      layers.findIndex((layer) => layer.bundle.id === scene.primary_bundle_id),
    );
    layers.forEach((layer) => usedBundleIds.add(layer.bundle.id));
    scenes.push({
      name: scene.name,
      relative_directory: scene.relative_directory,
      layers,
      primaryLayerIndex,
      image_files: layers.flatMap((layer) => layer.bundle.image_files),
      isScene: true,
    });
  }
  const standalone = bundles
    .filter((bundle) => !usedBundleIds.has(bundle.id))
    .map((bundle) => ({
      name: bundle.name,
      relative_directory: bundle.relative_directory,
      layers: [{ role: "main", bundle }],
      primaryLayerIndex: 0,
      image_files: bundle.image_files,
      isScene: false,
    }));
  return [...standalone, ...scenes].sort((left, right) => (
    left.relative_directory.localeCompare(right.relative_directory)
    || left.name.localeCompare(right.name)
  ));
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
  const entry = state.bundles[index];
  if (!entry) return;
  elements.actionSelect.disabled = true;
  elements.previousAnimation.disabled = true;
  elements.nextAnimation.disabled = true;
  elements.playButton.disabled = true;
  elements.resetButton.disabled = true;
  elements.timeRange.disabled = true;
  elements.stageEmpty.hidden = false;
  elements.stageEmpty.textContent = "Parsing skeleton";

  try {
    const loadedLayers = await Promise.all(entry.layers.map(loadSpineLayer));
    const primaryLayer = loadedLayers[entry.primaryLayerIndex];
    const missingTextureNames = new Set(
      loadedLayers.flatMap((layer) => [...layer.missingTextures]),
    );
    state.layers = loadedLayers;
    state.viewBounds = null;
    state.skeleton = primaryLayer.skeleton;
    state.animationState = primaryLayer.animationState;
    state.currentBundleIndex = index;
    state.currentAnimations = primaryLayer.skeletonData.animations;
    const firstAnimation = requestedAnimation
      || (state.currentAnimations.length ? state.currentAnimations[0].name : "");
    fillCurrentActionSelect();
    updateBundleSelection();
    if (firstAnimation) setActiveAnimation(firstAnimation);
    elements.bundleLabel.textContent = entry.isScene
      ? `${entry.relative_directory} / ${entry.layers.length} layers`
      : `${entry.relative_directory} / ${selectSkeletonFile(primaryLayer.bundle)}`;
    // Keep the canvas visible when only some attachments are unavailable.
    // The detailed missing-texture warning is shown in the sidebar instead.
    elements.stageEmpty.hidden = true;
    elements.stageEmpty.textContent = "";
    elements.actionSelect.disabled = state.currentAnimations.length === 0;
    elements.playButton.disabled = false;
    elements.resetButton.disabled = false;
    elements.timeRange.disabled = state.currentAnimations.length === 0;
    elements.playButton.textContent = state.playing ? "Pause" : "Play";
    updateSummary(entry);
    if (missingTextureNames.size) {
      elements.errorMessage.textContent = `Skeleton parsed, but texture data is not a browser image: ${[...missingTextureNames][0]}`;
      setStatus("Texture blocked", "status-warning");
    } else {
      setStatus("Runtime ready", "status-ready");
    }
    updateAnimationNavigation();
  } catch (error) {
    state.layers = [];
    state.viewBounds = null;
    state.skeleton = null;
    state.animationState = null;
    state.trackEntry = null;
    state.animationData = null;
    state.currentAnimations = [];
    state.duration = 0;
    showError(error);
    updateAnimationNavigation();
  }
}

async function loadSpineLayer(layerDefinition) {
  const { bundle, role } = layerDefinition;
  const atlasPath = bundlePath(bundle, selectAtlasFile(bundle));
  const skeletonPath = bundlePath(bundle, selectSkeletonFile(bundle));
  const atlasResponse = await fetch(assetUrl(atlasPath));
  if (!atlasResponse.ok) throw new Error(`Failed to load ${atlasPath} (${atlasResponse.status})`);
  const atlasText = await atlasResponse.text();
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
      missingTextures.add(path.split("/").pop());
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
  const skeleton = new spine.Skeleton(skeletonData);
  const animationStateData = new spine.AnimationStateData(skeletonData);
  return {
    bundle,
    role,
    skeletonData,
    skeleton,
    animationState: new spine.AnimationState(animationStateData),
    trackEntry: null,
    animationName: "",
    missingTextures: new Set(
      [...missingTextures].map((path) => path.split("/").pop()),
    ),
  };
}

function formatTime(seconds) {
  return `${Math.max(0, seconds).toFixed(2)}s`;
}

function fillBundleList() {
  state.bundleEntries = state.bundles.map((bundle, index) => {
    const displayName = bundle.name || bundle.relative_directory.split("/").pop();
    return { bundle, index, displayName, normalizedName: displayName.toLowerCase() };
  });
  state.filteredBundleEntries = state.bundleEntries;
  elements.animationList.scrollTop = 0;
  renderAnimationList();
  fillCurrentActionSelect();
}

function createAnimationListItem(entry, rowIndex) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "animation-item";
  button.dataset.bundleIndex = String(entry.index);
  button.setAttribute("role", "option");
  button.style.transform = `translateY(${rowIndex * ANIMATION_ROW_HEIGHT}px)`;
  const active = entry.index === state.currentBundleIndex;
  button.classList.toggle("is-active", active);
  button.setAttribute("aria-selected", String(active));

  const name = document.createElement("span");
  name.className = "animation-item-name";
  name.textContent = entry.displayName;
  const source = document.createElement("span");
  source.className = "animation-item-source";
  source.textContent = entry.bundle.relative_directory;
  const duration = document.createElement("span");
  duration.className = "animation-item-time";
  duration.textContent = entry.bundle.layers.length > 1
    ? `${entry.bundle.layers.length} layers`
    : `${entry.bundle.image_files.length} tex`;
  button.append(name, source, duration);
  return button;
}

function renderAnimationList() {
  const entries = state.filteredBundleEntries;
  elements.animationCount.textContent = String(entries.length);
  animationListContent.style.height = `${entries.length * ANIMATION_ROW_HEIGHT}px`;
  const viewportHeight = elements.animationList.clientHeight || 400;
  const start = Math.max(
    0,
    Math.floor(elements.animationList.scrollTop / ANIMATION_ROW_HEIGHT) - ANIMATION_LIST_OVERSCAN,
  );
  const end = Math.min(
    entries.length,
    Math.ceil((elements.animationList.scrollTop + viewportHeight) / ANIMATION_ROW_HEIGHT)
      + ANIMATION_LIST_OVERSCAN,
  );
  const fragment = document.createDocumentFragment();
  for (let index = start; index < end; index += 1) {
    fragment.append(createAnimationListItem(entries[index], index));
  }
  animationListContent.replaceChildren(fragment);
}

function queueAnimationListRender() {
  if (state.listRenderFrame) return;
  state.listRenderFrame = requestAnimationFrame(() => {
    state.listRenderFrame = 0;
    renderAnimationList();
  });
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

function updateSummary(entry) {
  const primaryBundle = entry.layers[entry.primaryLayerIndex].bundle;
  const values = [
    ["Animations", state.bundles.length],
    ["Layers", entry.layers.length],
    ["Skeleton", selectSkeletonFile(primaryBundle)],
    ["Textures", entry.image_files.length],
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
  updateAnimationNavigation();
}

function updateAnimationNavigation() {
  const entries = state.filteredBundleEntries;
  const currentPosition = entries.findIndex((entry) => entry.index === state.currentBundleIndex);
  elements.previousAnimation.disabled = currentPosition <= 0;
  elements.nextAnimation.disabled = currentPosition < 0 || currentPosition >= entries.length - 1;
}

function scrollAnimationIntoView(bundleIndex) {
  const rowIndex = state.filteredBundleEntries.findIndex((entry) => entry.index === bundleIndex);
  if (rowIndex < 0) return;
  const rowTop = rowIndex * ANIMATION_ROW_HEIGHT;
  const rowBottom = rowTop + ANIMATION_ROW_HEIGHT;
  const viewportTop = elements.animationList.scrollTop;
  const viewportBottom = viewportTop + elements.animationList.clientHeight;
  if (rowTop < viewportTop) {
    elements.animationList.scrollTop = rowTop;
  } else if (rowBottom > viewportBottom) {
    elements.animationList.scrollTop = rowBottom - elements.animationList.clientHeight;
  }
  renderAnimationList();
}

async function navigateAnimation(direction) {
  if (elements.previousAnimation.disabled && direction < 0) return;
  if (elements.nextAnimation.disabled && direction > 0) return;
  const currentPosition = state.filteredBundleEntries.findIndex(
    (entry) => entry.index === state.currentBundleIndex,
  );
  const target = state.filteredBundleEntries[currentPosition + direction];
  if (!target) return;
  await loadBundle(target.index);
  if (state.currentBundleIndex === target.index) {
    scrollAnimationIntoView(target.index);
  }
}

function updateTimeline() {
  const trackTime = state.trackEntry?.trackTime ?? 0;
  const visibleTime = elements.loopToggle.checked && state.duration > 0
    ? Math.max(trackTime, 0) % state.duration
    : Math.min(Math.max(trackTime, 0), state.duration);
  elements.timeRange.max = String(Math.max(state.duration, 0.001));
  elements.timeRange.value = String(visibleTime);
  elements.timeValue.textContent = formatTime(visibleTime);
  elements.durationValue.textContent = formatTime(state.duration);
  elements.durationLabel.textContent = formatTime(state.duration);
  elements.durationValue.title = state.animationName || "No animation";
}

function setActiveAnimation(name) {
  if (!state.layers.length || !state.skeleton) return;
  const animation = state.skeleton.data.animations.find((item) => item.name === name);
  if (!animation) return;
  state.animationName = name;
  state.animationData = animation;
  state.duration = 0;
  state.trackEntry = null;
  const currentEntry = state.bundles[state.currentBundleIndex];
  for (const [index, layer] of state.layers.entries()) {
    const layerAnimation = selectLayerAnimation(
      layer,
      name,
      index === currentEntry.primaryLayerIndex,
    );
    layer.skeleton.setToSetupPose();
    if (!layerAnimation) {
      layer.trackEntry = null;
      layer.animationName = "";
      continue;
    }
    layer.animationName = layerAnimation.name;
    layer.trackEntry = layer.animationState.setAnimation(
      0,
      layerAnimation.name,
      elements.loopToggle.checked,
    );
    state.duration = Math.max(state.duration, layerAnimation.duration);
    if (index === currentEntry.primaryLayerIndex) {
      state.trackEntry = layer.trackEntry;
    }
  }
  state.viewBounds = calculateStableViewBounds();
  state.lastTime = performance.now();
  updateBundleSelection();
  updateTimeline();
}

function selectLayerAnimation(layer, requestedName, isPrimary) {
  const animations = layer.skeletonData.animations;
  if (!animations.length) return null;
  const exact = animations.find((animation) => animation.name === requestedName);
  if (exact || isPrimary) return exact ?? animations[0];
  if (layer.role === "background") {
    if (/show/i.test(requestedName)) {
      const showAnimation = animations.find((animation) => /bgshow|show/i.test(animation.name));
      if (showAnimation) return showAnimation;
    }
    const backgroundAnimation = animations.find((animation) => /^bg$/i.test(animation.name));
    if (backgroundAnimation) return backgroundAnimation;
  }
  return animations[0];
}

function currentSkeletonBounds() {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const layer of state.layers) {
    const boundsOffset = new spine.Vector2();
    const boundsSize = new spine.Vector2();
    layer.skeleton.getBounds(boundsOffset, boundsSize);
    minX = Math.min(minX, boundsOffset.x);
    minY = Math.min(minY, boundsOffset.y);
    maxX = Math.max(maxX, boundsOffset.x + boundsSize.x);
    maxY = Math.max(maxY, boundsOffset.y + boundsSize.y);
  }
  if (![minX, minY, maxX, maxY].every(Number.isFinite)) return null;
  return { minX, minY, maxX, maxY };
}

function calculateStableViewBounds() {
  if (!state.layers.length) return null;
  const sampleCount = Math.min(40, Math.max(2, Math.ceil(state.duration * 8)));
  let stableBounds = null;
  for (let sample = 0; sample <= sampleCount; sample += 1) {
    const sampleTime = state.duration * sample / sampleCount;
    for (const layer of state.layers) {
      layer.skeleton.setToSetupPose();
      if (layer.trackEntry) {
        const animation = layer.skeletonData.animations.find(
          (item) => item.name === layer.animationName,
        );
        const animationDuration = animation?.duration ?? 0;
        layer.trackEntry.trackTime = elements.loopToggle.checked && animationDuration > 0
          ? sampleTime % animationDuration
          : Math.min(sampleTime, animationDuration);
        layer.animationState.apply(layer.skeleton);
      }
      layer.skeleton.updateWorldTransform();
    }
    const sampleBounds = currentSkeletonBounds();
    if (!sampleBounds) continue;
    if (!stableBounds) {
      stableBounds = { ...sampleBounds };
      continue;
    }
    stableBounds.minX = Math.min(stableBounds.minX, sampleBounds.minX);
    stableBounds.minY = Math.min(stableBounds.minY, sampleBounds.minY);
    stableBounds.maxX = Math.max(stableBounds.maxX, sampleBounds.maxX);
    stableBounds.maxY = Math.max(stableBounds.maxY, sampleBounds.maxY);
  }
  for (const layer of state.layers) {
    layer.skeleton.setToSetupPose();
    if (layer.trackEntry) {
      layer.trackEntry.trackTime = 0;
      layer.animationState.apply(layer.skeleton);
    }
    layer.skeleton.updateWorldTransform();
  }
  return stableBounds ?? currentSkeletonBounds();
}

function applyCurrentPose() {
  if (!state.layers.length) return;
  for (const layer of state.layers) {
    layer.animationState.apply(layer.skeleton);
    layer.skeleton.updateWorldTransform();
  }
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
  if (!state.layers.length) return;

  const bounds = state.viewBounds ?? currentSkeletonBounds();
  if (!bounds) return;
  const { minX, minY, maxX, maxY } = bounds;
  const boundsWidth = Math.max(maxX - minX, 1);
  const boundsHeight = Math.max(maxY - minY, 1);
  const scale = Math.min(
    elements.canvas.width / boundsWidth,
    elements.canvas.height / boundsHeight,
  ) * 0.78 * state.scale;
  const boundsCenterX = minX + boundsWidth / 2;
  const boundsCenterY = minY + boundsHeight / 2;

  gl.useProgram(renderer.program);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
  gl.disable(gl.DEPTH_TEST);
  gl.disable(gl.CULL_FACE);
  gl.activeTexture(gl.TEXTURE0);
  gl.uniform1i(renderer.samplerLocation, 0);

  for (const layer of state.layers) {
    drawSkeletonLayer(layer.skeleton, boundsCenterX, boundsCenterY, scale);
  }
}

function drawSkeletonLayer(skeleton, boundsCenterX, boundsCenterY, scale) {
  for (const slot of skeleton.drawOrder) {
    const attachment = slot.getAttachment();
    if (attachment instanceof spine.RegionAttachment) {
      const vertices = new Float32Array(8);
      attachment.computeWorldVertices(slot.bone, vertices, 0, 2);
      drawTexturedAttachment(
        skeleton,
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
        skeleton,
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
  skeleton,
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

  const skeletonColor = skeleton.color;
  const alpha = skeletonColor.a * slot.color.a * attachment.color.a;
  gl.uniform4f(
    renderer.colorLocation,
    skeletonColor.r * slot.color.r * attachment.color.r * alpha,
    skeletonColor.g * slot.color.g * attachment.color.g * alpha,
    skeletonColor.b * slot.color.b * attachment.color.b * alpha,
    alpha,
  );
  gl.drawElements(gl.TRIANGLES, triangles.length, gl.UNSIGNED_SHORT, 0);
}

function frame(now) {
  const delta = Math.min((now - state.lastTime) / 1000, 0.1);
  state.lastTime = now;
  if (state.layers.length && state.playing) {
    for (const layer of state.layers) {
      layer.animationState.update(delta * state.speed);
      layer.animationState.apply(layer.skeleton);
      layer.skeleton.updateWorldTransform();
    }
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
elements.animationList.addEventListener("scroll", queueAnimationListRender, { passive: true });
elements.animationSearch.addEventListener("input", () => {
  if (state.listFilterFrame) cancelAnimationFrame(state.listFilterFrame);
  state.listFilterFrame = requestAnimationFrame(() => {
    state.listFilterFrame = 0;
    const query = elements.animationSearch.value.trim().toLowerCase();
    state.filteredBundleEntries = query
      ? state.bundleEntries.filter((entry) => entry.normalizedName.includes(query))
      : state.bundleEntries;
    elements.animationList.scrollTop = 0;
    renderAnimationList();
    updateAnimationNavigation();
  });
});
window.addEventListener("resize", queueAnimationListRender);
elements.previousAnimation.addEventListener("click", () => navigateAnimation(-1));
elements.nextAnimation.addEventListener("click", () => navigateAnimation(1));
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
  const trackTime = Number(elements.timeRange.value);
  for (const layer of state.layers) {
    if (layer.trackEntry) layer.trackEntry.trackTime = trackTime;
  }
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
    state.bundles = buildPlayerEntries(state.manifest);
    if (!state.bundles.length) throw new Error("No complete Spine animations found in the extracted output");
    fillBundleList();
    await loadBundle(0);
  } catch (error) {
    showError(error);
  }
  requestAnimationFrame(frame);
}

bootstrap();
