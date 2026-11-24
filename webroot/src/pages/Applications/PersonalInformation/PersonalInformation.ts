//
//  PersonalInformation.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import { Component, mixins, toNative } from 'vue-facing-decorator';
import { reactive, computed } from 'vue';
import MixinApplicationSection, { SelectOption } from '@pages/Applications/_mixins/applicationSection.mixin';
import ApplicationSectionLayout from '@components/ApplicationSectionLayout/ApplicationSectionLayout.vue';
import InputText from '@components/Forms/InputText/InputText.vue';
import InputSelect from '@components/Forms/InputSelect/InputSelect.vue';
import InputDate from '@components/Forms/InputDate/InputDate.vue';
import InputPhone from '@components/Forms/InputPhone/InputPhone.vue';
import CloseXIcon from '@components/Icons/CloseX/CloseX.vue';
import { ApplicationSection } from '@models/Application/Application.model';
import { FormInput } from '@models/FormInput/FormInput.model';
import { countries as countryData } from 'country-codes-flags-phone-codes';
import Joi from 'joi';

interface LocaleOption {
    key?: string;
    name?: string;
    abbrev?: string;
}

@Component({
    name: 'PersonalInformation',
    components: {
        ApplicationSectionLayout,
        InputText,
        InputSelect,
        InputDate,
        InputPhone,
        CloseXIcon,
    },
})
class PersonalInformation extends mixins(MixinApplicationSection) {
    //
    // Data
    //
    sectionKey = ApplicationSection.PERSONAL_INFORMATION;

    //
    // Computed
    //
    get suffixOptions(): Array<SelectOption> {
        const suffixes: Array<LocaleOption> = this.$tm('application.suffixOptions') || [];

        return suffixes.map(({ key = '', name = '' }) => ({ value: key, name }));
    }

    get genderOptions(): Array<SelectOption> {
        const genders: Array<LocaleOption> = this.$tm('application.genderOptions') || [];

        return [
            { value: '', name: `- ${this.$t('common.select')} -` },
            ...genders.map(({ key = '', name = '' }) => ({ value: key, name })),
        ];
    }

    get citizenshipOptions(): Array<SelectOption> {
        const countries: Array<LocaleOption> = this.$tm('countries') || [];

        return [
            { value: '', name: `- ${this.$t('common.select')} -` },
            ...countries.map(({ abbrev = '', name = '' }) => {
                const flag = countryData.find((country) => country.code === abbrev.toUpperCase())?.flag;

                return {
                    value: abbrev.toLowerCase(),
                    name: (flag) ? `${flag} ${name}` : name,
                };
            }),
        ];
    }

    get languageOptions(): Array<SelectOption> {
        const languages: Array<LocaleOption> = this.$tm('languages') || [];

        return languages.map(({ abbrev = '', name = '' }) => ({ value: abbrev.toLowerCase(), name }));
    }

    get selectedLanguages(): Array<string> {
        return (this.formData.languages?.value as Array<string>) || [];
    }

    get selectedLanguageOptions(): Array<SelectOption> {
        return this.selectedLanguages.map((language) =>
            this.languageOptions.find((option) => option.value === language) || { value: language, name: language });
    }

    get availableLanguageOptions(): Array<SelectOption> {
        return [
            { value: '', name: this.$t('application.languagesPlaceholder'), isDisabled: true },
            ...this.languageOptions.filter((option) => !this.selectedLanguages.includes(option.value as string)),
        ];
    }

    //
    // Methods
    //
    initFormInputs(): void {
        const personalInformation = this.applicationData.personalInformation || {} as any;

        this.formData = reactive({
            firstName: new FormInput({
                id: 'first-name',
                name: 'first-name',
                label: computed(() => this.$t('application.firstNameLabel')),
                autocomplete: 'given-name',
                value: personalInformation.firstName || '',
                validation: this.textValidation(),
            }),
            lastName: new FormInput({
                id: 'last-name',
                name: 'last-name',
                label: computed(() => this.$t('application.lastNameLabel')),
                autocomplete: 'family-name',
                value: personalInformation.lastName || '',
                validation: this.textValidation(),
            }),
            middleName: new FormInput({
                id: 'middle-name',
                name: 'middle-name',
                label: computed(() => this.$t('application.middleNameLabel')),
                autocomplete: 'additional-name',
                value: personalInformation.middleName || '',
                validation: this.textValidation({ isRequired: false }),
            }),
            suffix: new FormInput({
                id: 'suffix',
                name: 'suffix',
                label: computed(() => this.$t('application.suffixLabel')),
                value: personalInformation.suffix || '',
                valueOptions: this.suffixOptions,
            }),
            dob: new FormInput({
                id: 'dob',
                name: 'dob',
                label: computed(() => this.$t('application.dobLabel')),
                placeholder: 'MM/DD/YYYY',
                autocomplete: 'bday',
                value: personalInformation.dob || '',
                validation: this.dateValidation(),
            }),
            gender: new FormInput({
                id: 'gender',
                name: 'gender',
                label: computed(() => this.$t('application.genderLabel')),
                value: personalInformation.gender || '',
                valueOptions: this.genderOptions,
                validation: Joi.string().required().messages(this.joiMessages.string),
            }),
            professionalName: new FormInput({
                id: 'professional-name',
                name: 'professional-name',
                label: computed(() => this.$t('application.professionalNameLabel')),
                placeholder: computed(() => this.$t('application.professionalNamePlaceholder')),
                value: personalInformation.professionalName || '',
                validation: this.textValidation(),
            }),
            ssnLastFour: new FormInput({
                id: 'ssn-last-four',
                name: 'ssn-last-four',
                label: computed(() => this.$t('application.ssnLastFourLabel')),
                autocomplete: 'off',
                value: personalInformation.ssnLastFour || '',
                validation: this.numericValidation(4),
                enforceMax: true,
            }),
            citizenship: new FormInput({
                id: 'citizenship',
                name: 'citizenship',
                label: computed(() => this.$t('application.citizenshipLabel')),
                value: personalInformation.citizenship || '',
                valueOptions: this.citizenshipOptions,
            }),
            placeOfBirth: new FormInput({
                id: 'place-of-birth',
                name: 'place-of-birth',
                label: computed(() => this.$t('application.placeOfBirthLabel')),
                placeholder: computed(() => this.$t('application.placeOfBirthPlaceholder')),
                value: personalInformation.placeOfBirth || '',
                validation: this.textValidation({ isRequired: false }),
            }),
            npi: new FormInput({
                id: 'npi',
                name: 'npi',
                label: computed(() => this.$t('application.npiLabel')),
                placeholder: computed(() => this.$t('application.npiPlaceholder')),
                autocomplete: 'off',
                value: personalInformation.npi || '',
                validation: this.numericValidation(10, false),
            }),
            languageSelect: new FormInput({
                id: 'language-select',
                name: 'language-select',
                label: computed(() => this.$t('application.languagesLabel')),
                value: '',
                valueOptions: this.availableLanguageOptions,
            }),
            languages: new FormInput({
                id: 'languages',
                name: 'languages',
                value: [...(personalInformation.languages || [])],
            }),
            mailingAddress1: new FormInput({
                id: 'mailing-address-1',
                name: 'mailing-address-1',
                label: computed(() => this.$t('application.mailingAddressLabel')),
                placeholder: computed(() => this.$t('application.mailingAddressPlaceholder')),
                autocomplete: 'address-line1',
                value: personalInformation.mailingAddress1 || '',
                validation: this.textValidation(),
            }),
            mailingAddress2: new FormInput({
                id: 'mailing-address-2',
                name: 'mailing-address-2',
                label: computed(() => this.$t('application.addressLine2Label')),
                placeholder: computed(() => this.$t('application.addressLine2Placeholder')),
                autocomplete: 'address-line2',
                value: personalInformation.mailingAddress2 || '',
                validation: this.textValidation({ isRequired: false }),
            }),
            mailingCity: new FormInput({
                id: 'mailing-city',
                name: 'mailing-city',
                label: computed(() => this.$t('application.cityLabel')),
                autocomplete: 'address-level2',
                value: personalInformation.mailingCity || '',
                validation: this.textValidation(),
            }),
            mailingState: new FormInput({
                id: 'mailing-state',
                name: 'mailing-state',
                label: computed(() => this.$t('application.stateLabel')),
                autocomplete: 'address-level1',
                value: personalInformation.mailingState || '',
                valueOptions: this.getStateOptions(this.$t('common.selectOption')),
                validation: Joi.string().required().messages(this.joiMessages.string),
            }),
            mailingZip: new FormInput({
                id: 'mailing-zip',
                name: 'mailing-zip',
                label: computed(() => this.$t('application.zipLabel')),
                autocomplete: 'postal-code',
                value: personalInformation.mailingZip || '',
                validation: Joi.string().required().max(10).pattern(/^\d{5}(-\d{4})?$/)
                    .messages({
                        ...this.joiMessages.string,
                        'string.pattern.base': this.$t('application.zipFormat'),
                    }),
                enforceMax: true,
            }),
            phone: new FormInput({
                id: 'phone',
                name: 'phone',
                label: computed(() => this.$t('application.phoneLabel')),
                autocomplete: 'tel',
                value: personalInformation.phone || '',
                validation: this.phoneValidation(),
            }),
            altPhone: new FormInput({
                id: 'alt-phone',
                name: 'alt-phone',
                label: computed(() => this.$t('application.altPhoneLabel')),
                autocomplete: 'tel',
                value: personalInformation.altPhone || '',
                validation: this.phoneValidation(false),
            }),
            submit: new FormInput({
                isSubmitInput: true,
                id: 'submit-personal-information',
            }),
        });
        this.refreshLanguageOptions();
        this.watchFormInputs();
    }

    addLanguage(): void {
        const { languageSelect, languages } = this.formData;
        const language = languageSelect.value;

        if (language && !this.selectedLanguages.includes(language)) {
            languages.value = [...this.selectedLanguages, language];
        }

        languageSelect.value = '';
        this.refreshLanguageOptions();
    }

    removeLanguage(language: string): void {
        this.formData.languages.value = this.selectedLanguages.filter((selected) => selected !== language);
        this.refreshLanguageOptions();
    }

    mockPopulate(): void {
        const { formData } = this;

        formData.firstName.value = 'Test';
        formData.middleName.value = 'Mock';
        formData.lastName.value = 'Applicant';
        formData.suffix.value = '';
        formData.dob.value = '1980-05-15';
        formData.gender.value = 'female';
        formData.professionalName.value = 'Test Applicant, PsyD';
        formData.ssnLastFour.value = '1234';
        formData.citizenship.value = 'us';
        formData.placeOfBirth.value = 'Denver, CO';
        formData.npi.value = '1234567890';
        formData.languages.value = ['en', 'es'];
        formData.mailingAddress1.value = '123 Mock St';
        formData.mailingAddress2.value = 'Suite 100';
        formData.mailingCity.value = 'Denver';
        formData.mailingState.value = 'co';
        formData.mailingZip.value = '80202';
        formData.phone.value = '+13035551234';
        formData.altPhone.value = '';
        this.refreshLanguageOptions();
    }

    afterClearForm(): void {
        this.refreshLanguageOptions();
    }

    refreshLanguageOptions(): void {
        this.formData.languageSelect.valueOptions = this.availableLanguageOptions;
    }

    prepSectionRequestData(): object {
        const { formValues } = this;

        return {
            firstName: formValues.firstName,
            middleName: this.valueOrNull(formValues.middleName),
            lastName: formValues.lastName,
            suffix: this.valueOrNull(formValues.suffix),
            phone: formValues.phone,
            altPhone: this.valueOrNull(formValues.altPhone),
            dob: formValues.dob,
            ssnLastFour: formValues.ssnLastFour,
            npi: this.valueOrNull(formValues.npi),
            gender: formValues.gender,
            professionalName: formValues.professionalName,
            citizenship: this.valueOrNull(formValues.citizenship),
            placeOfBirth: this.valueOrNull(formValues.placeOfBirth),
            languages: formValues.languages,
            mailingAddress1: formValues.mailingAddress1,
            mailingAddress2: this.valueOrNull(formValues.mailingAddress2),
            mailingCity: formValues.mailingCity,
            mailingState: formValues.mailingState,
            mailingZip: formValues.mailingZip,
        };
    }
}

export default toNative(PersonalInformation);

// export default PersonalInformation;
