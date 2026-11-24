//
//  InputPhone.ts
//  InspiringApps modules
//
//  Created by InspiringApps on 6/19/2020.
//

import {
    Component,
    mixins,
    Watch,
    toNative
} from 'vue-facing-decorator';
import { reactive } from 'vue';
import MixinInput from '@components/Forms/_mixins/input.mixin';
import InputSelect from '@components/Forms/InputSelect/InputSelect.vue';
import { FormInput } from '@models/FormInput/FormInput.model';
import { countries as countryData } from 'country-codes-flags-phone-codes';
import { AsYouType, parsePhoneNumber, CountryCode } from 'libphonenumber-js';

@Component({
    name: 'InputPhone',
    components: {
        InputSelect,
    },
})
class InputPhone extends mixins(MixinInput) {
    //
    // Data
    //
    formData: any = {};
    localValue = '';

    //
    // Lifecycle
    //
    created() {
        this.initFormInputs();
        this.syncFromValue(this.formInput.value);
    }

    //
    // Computed
    //
    get countryCodes(): Array<{ value: string, name: string }> {
        const allowedCountryCodes = ['US'];
        const allowedCountries = countryData.filter((country) => allowedCountryCodes.includes(country.code));
        const sortedCountries = allowedCountries.sort((a, b) =>
            allowedCountryCodes.indexOf(a.code) - allowedCountryCodes.indexOf(b.code));
        const countries = sortedCountries.map((country) => ({
            value: country.code,
            name: `${country.flag} ${country.dialCode}`,
        }));

        return countries;
    }

    get selectedCountry(): CountryCode {
        return this.formData.country?.value || 'US';
    }

    get phoneRaw(): string {
        const { selectedCountry } = this;
        let raw = '';

        try {
            const parsed = parsePhoneNumber(this.localValue, selectedCountry);

            raw = parsed.number;
        } catch (e) {
            // Continue
        }

        return raw;
    }

    get isPhoneValid(): boolean {
        const { selectedCountry } = this;
        let isValid = false;

        try {
            const parsed = parsePhoneNumber(this.localValue, selectedCountry);

            isValid = parsed.isValid();
        } catch (e) {
            // Continue
        }

        return isValid;
    }

    //
    // Watchers
    //
    @Watch('formInput.value')
    onFormInputValueChange(value: string): void {
        if ((value || '') !== this.phoneRaw) {
            this.syncFromValue(value);
        }
    }

    //
    // Methods
    //
    initFormInputs(): void {
        this.formData = reactive({
            country: new FormInput({
                id: 'country',
                name: 'country',
                label: 'country',
                shouldHideLabel: true,
                value: this.countryCodes[0]?.value || '',
                valueOptions: this.countryCodes,
            }),
        });
    }

    syncFromValue(value = ''): void {
        let displayValue = value || '';

        try {
            const parsed = parsePhoneNumber(displayValue, this.selectedCountry);
            const isAllowedCountry = this.countryCodes.some((country) => country.value === parsed.country);

            if (isAllowedCountry) {
                this.formData.country.value = parsed.country;
            }

            displayValue = parsed.formatNational();
        } catch (e) {
            // Continue
        }

        this.localValue = displayValue;
    }

    emitValue(): void {
        this.formInput.value = this.phoneRaw;
        this.validate();
    }

    validate(): void {
        const { isPhoneValid, formInput, isRequired } = this;
        const isEmptyOptional = !this.localValue && !isRequired;

        if (!isPhoneValid && formInput.isTouched && !isEmptyOptional) {
            formInput.errorMessage = this.$t('inputErrors.phone');
            formInput.isValid = false;
        } else {
            formInput.errorMessage = ``;
            formInput.isValid = true;
        }
    }

    input(): void {
        this.emitValue();
    }

    blur(formInput: FormInput): void {
        formInput.isTouched = true;

        if (this.phoneRaw) {
            this.syncFromValue(this.phoneRaw);
        } else {
            this.localValue = new AsYouType(this.selectedCountry).input(this.localValue);
        }

        this.validate();
    }

    inputCountry(): void {
        this.emitValue();
    }

    blurCountry(): void {
        this.validate();
    }
}

export default toNative(InputPhone);

// export { InputPhone };
