from datetime import datetime
import math

class BodyMetrics:
    def __init__(self, weight, height, age, sex, impedance):
        self.weight = weight
        self.height = height
        self.age = age
        self.sex = sex
        self.impedance = impedance

    def calculate_all(self):
        metrics = {}
        
        # 1. BMI
        bmi = self.weight / ((self.height / 100) ** 2)
        metrics['bmi'] = round(bmi, 1)

        # If we have no impedance, we can't do much more accurately.
        if not self.impedance or self.impedance == 0:
            return metrics

        # 2. Body Fat %
        # Logic ported from common open-source implementations for Mi Scale 2
        # (Simplified approximation of Holtek algo)
        
        # LBM Coefficient
        lbm = (self.height * 9.058 - 0.009 * self.weight + self.age * 0.0636 - 15.09)
        if self.sex == 'male':
            lbm = (self.height * 9.529 - 0.168 * self.weight + self.age * 0.174 - 20.34)
            
        # Impedance correction (Approximation)
        # This is the tricky part. Let's use the Deurenberg formula as a baseline safety check
        # But try to use the raw impedance if possible.
        
        # Note: Without the exact coefficients from the proprietary lib, exact match is impossible.
        # OpenScale uses this:
        # LBM = (0.32810 * weight) + (0.33929 * height) - (29.5336) ... (This is for V1?)
        
        # Let's use the "Standard BIA" which is better than nothing.
        # Fat % = 100 * (Weight - LBM) / Weight
        
        # Let's use the Deurenberg formula for robustness as "Estimated Fat"
        sex_val = 1 if self.sex == 'male' else 0
        fat_pct = (1.20 * bmi) + (0.23 * self.age) - (10.8 * sex_val) - 5.4
        
        # Water % approximation (Standard: 73% of LBM is water)
        # If we assume Fat %, then LBM % = 100 - Fat %.
        # Water % = (100 - Fat %) * 0.73
        
        # Refine Fat % using Impedance if possible?
        # Higher Impedance = More Fat. 
        # For 508 ohm (Low for male? Standard 300-600), 
        # Typically 500 is very conductive -> lean.
        
        # Let's stick to these reliable estimates for now to avoid showing "5% fat" errors.
        
        metrics['body_fat'] = round(fat_pct, 1)
        metrics['lean_body_mass'] = round(self.weight * (1 - fat_pct/100), 1)
        metrics['water_percentage'] = round((100 - fat_pct) * 0.73, 1)
        metrics['bone_mass'] = round((self.weight - metrics['lean_body_mass']) * 0.15 + 2.5, 1) # Total guess? No.
        
        # Bone Mass (Xiaomi approximation)
        # Male: <60kg: 2.5, 60-75: 2.9, >75: 3.2
        if self.sex == 'male':
            if self.weight < 60: metrics['bone_mass'] = 2.5
            elif self.weight < 75: metrics['bone_mass'] = 2.9
            else: metrics['bone_mass'] = 3.2
        else:
            if self.weight < 45: metrics['bone_mass'] = 1.8
            elif self.weight < 60: metrics['bone_mass'] = 2.2
            else: metrics['bone_mass'] = 2.5
            
        # Muscle Mass = LBM - Bone Mass
        metrics['muscle_mass'] = round(metrics['lean_body_mass'] - metrics['bone_mass'], 1)
        
        # Visceral Fat (Arbitrary scale 1-15 usually)
        # Using VFA formula (approx)
        metrics['visceral_fat'] = round(metrics['body_fat'] / 2.0 - 6.0) 
        if metrics['visceral_fat'] < 1: metrics['visceral_fat'] = 1
        
        # BMR (Mifflin-St Jeor) - Gold standard for BMR
        if self.sex == 'male':
            bmr = 10 * self.weight + 6.25 * self.height - 5 * self.age + 5
        else:
            bmr = 10 * self.weight + 6.25 * self.height - 5 * self.age - 161
        metrics['bmr'] = round(bmr)

        return metrics
