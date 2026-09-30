/**
 * Traveling-wave Gaussian pulse fragment shader (Shortlist §14).
 *
 *   pulseIntensity = exp( -((a_progress - fract((u_time - a_spikeTime) * v_speed))^2) / (2 σ²) )
 *
 * Geometry/AA pattern ported from MIT-licensed sigma.js edge-rectangle.
 */
const SHADER_SOURCE = /*glsl*/ `
precision mediump float;

varying vec4 v_color;
varying vec2 v_normal;
varying float v_thickness;
varying float v_feather;
varying float v_progress;
varying float v_spikeTime;
varying float v_pulseSpeed;

uniform float u_time;
uniform float u_pulseSigma;

const vec4 transparent = vec4(0.0, 0.0, 0.0, 0.0);
const vec3 pulseTint = vec3(0.4, 1.0, 0.85);

void main(void) {
  #ifdef PICKING_MODE
  gl_FragColor = v_color;
  #else
  float dist = length(v_normal) * v_thickness;
  float t = smoothstep(v_thickness - v_feather, v_thickness, dist);

  float speed = max(v_pulseSpeed, 0.05);
  float phase = fract((u_time - v_spikeTime) * speed);
  float sigma = max(u_pulseSigma, 0.02);
  float d = v_progress - phase;
  float pulseIntensity = exp(-(d * d) / (2.0 * sigma * sigma));

  // Suppress idle glow when spike is ancient / unset
  float active = step(0.0, u_time - v_spikeTime);
  pulseIntensity *= active;

  vec3 base = v_color.rgb;
  vec3 lit = mix(base, pulseTint, clamp(pulseIntensity, 0.0, 1.0));
  float alpha = mix(v_color.a, 1.0, pulseIntensity * 0.85);

  gl_FragColor = mix(vec4(lit, alpha), transparent, t);
  #endif
}
`;

export default SHADER_SOURCE;
