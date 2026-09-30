/**
 * Instanced WebGL edge pulse program — algorithm/geometry ported from
 * jacomyal/sigma.js edge-rectangle (MIT). Adds traveling-wave pulse attrs.
 * No GPL code.
 */

import type { Attributes } from "graphology-types";
import type { EdgeDisplayData, NodeDisplayData, RenderParams } from "sigma/types";
import { EdgeProgram, type ProgramInfo } from "sigma/rendering";
import { floatColor } from "sigma/utils";
import VERTEX_SHADER_SOURCE from "./edge-pulse.vert.js";
import FRAGMENT_SHADER_SOURCE from "./edge-pulse.frag.js";

const { UNSIGNED_BYTE, FLOAT } = WebGLRenderingContext;

const UNIFORMS = [
  "u_matrix",
  "u_zoomRatio",
  "u_sizeRatio",
  "u_correctionRatio",
  "u_pixelRatio",
  "u_feather",
  "u_minEdgeThickness",
  "u_time",
  "u_pulseSigma",
] as const;

export interface PulseEdgeDisplayData extends EdgeDisplayData {
  spikeTime?: number;
  pulseSpeed?: number;
}

/** Shared clock so setUniforms can advance without reallocating. */
let sharedTimeSeconds = 0;

export function advancePulseTime(dtSeconds: number): void {
  sharedTimeSeconds += dtSeconds;
}

export function setPulseTime(seconds: number): void {
  sharedTimeSeconds = seconds;
}

export function getPulseTime(): number {
  return sharedTimeSeconds;
}

export default class EdgePulseProgram<
  N extends Attributes = Attributes,
  E extends Attributes = Attributes,
  G extends Attributes = Attributes,
> extends EdgeProgram<(typeof UNIFORMS)[number], N, E, G> {
  getDefinition() {
    return {
      VERTICES: 6,
      VERTEX_SHADER_SOURCE,
      FRAGMENT_SHADER_SOURCE,
      METHOD: WebGLRenderingContext.TRIANGLES,
      UNIFORMS,
      ATTRIBUTES: [
        { name: "a_positionStart", size: 2, type: FLOAT },
        { name: "a_positionEnd", size: 2, type: FLOAT },
        { name: "a_normal", size: 2, type: FLOAT },
        { name: "a_color", size: 4, type: UNSIGNED_BYTE, normalized: true },
        { name: "a_id", size: 4, type: UNSIGNED_BYTE, normalized: true },
        { name: "a_spikeTime", size: 1, type: FLOAT },
        { name: "a_pulseSpeed", size: 1, type: FLOAT },
      ],
      CONSTANT_ATTRIBUTES: [
        { name: "a_positionCoef", size: 1, type: FLOAT },
        { name: "a_normalCoef", size: 1, type: FLOAT },
      ],
      CONSTANT_DATA: [
        [0, 1],
        [0, -1],
        [1, 1],
        [1, 1],
        [0, -1],
        [1, -1],
      ],
    };
  }

  processVisibleItem(
    edgeIndex: number,
    startIndex: number,
    sourceData: NodeDisplayData,
    targetData: NodeDisplayData,
    data: PulseEdgeDisplayData,
  ): void {
    const thickness = data.size || 1;
    const x1 = sourceData.x;
    const y1 = sourceData.y;
    const x2 = targetData.x;
    const y2 = targetData.y;
    const color = floatColor(data.color);
    const spikeTime = data.spikeTime ?? -1e9;
    const pulseSpeed = data.pulseSpeed ?? 0.35;

    const dx = x2 - x1;
    const dy = y2 - y1;
    let len = dx * dx + dy * dy;
    let n1 = 0;
    let n2 = 0;
    if (len) {
      len = 1 / Math.sqrt(len);
      n1 = -dy * len * thickness;
      n2 = dx * len * thickness;
    }

    const array = this.array;
    array[startIndex++] = x1;
    array[startIndex++] = y1;
    array[startIndex++] = x2;
    array[startIndex++] = y2;
    array[startIndex++] = n1;
    array[startIndex++] = n2;
    array[startIndex++] = color;
    array[startIndex++] = edgeIndex;
    array[startIndex++] = spikeTime;
    array[startIndex++] = pulseSpeed;
  }

  setUniforms(params: RenderParams, { gl, uniformLocations }: ProgramInfo): void {
    const {
      u_matrix,
      u_zoomRatio,
      u_feather,
      u_pixelRatio,
      u_correctionRatio,
      u_sizeRatio,
      u_minEdgeThickness,
      u_time,
      u_pulseSigma,
    } = uniformLocations;

    gl.uniformMatrix3fv(u_matrix, false, params.matrix);
    gl.uniform1f(u_zoomRatio, params.zoomRatio);
    gl.uniform1f(u_sizeRatio, params.sizeRatio);
    gl.uniform1f(u_correctionRatio, params.correctionRatio);
    gl.uniform1f(u_pixelRatio, params.pixelRatio);
    gl.uniform1f(u_feather, params.antiAliasingFeather);
    gl.uniform1f(u_minEdgeThickness, params.minEdgeThickness);
    gl.uniform1f(u_time, sharedTimeSeconds);
    gl.uniform1f(u_pulseSigma, 0.08);
  }
}
