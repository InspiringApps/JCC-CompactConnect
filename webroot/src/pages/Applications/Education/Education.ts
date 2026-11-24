//
//  Education.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import {
    Component, mixins, toNative, Watch
} from 'vue-facing-decorator';
import { reactive, computed } from 'vue';
import MixinApplicationSection, { SelectOption } from '@pages/Applications/_mixins/applicationSection.mixin';
import ApplicationSectionLayout from '@components/ApplicationSectionLayout/ApplicationSectionLayout.vue';
import ApplicationQuestionRow from '@components/ApplicationQuestionRow/ApplicationQuestionRow.vue';
import InputText from '@components/Forms/InputText/InputText.vue';
import InputSelect from '@components/Forms/InputSelect/InputSelect.vue';
import InputDate from '@components/Forms/InputDate/InputDate.vue';
import InputPhone from '@components/Forms/InputPhone/InputPhone.vue';
import InputCheckbox from '@components/Forms/InputCheckbox/InputCheckbox.vue';
import InfoCircleIcon from '@components/Icons/InfoCircle/InfoCircle.vue';
import { ApplicationAccreditingContact, ApplicationSection } from '@models/Application/Application.model';
import { FormInput } from '@models/FormInput/FormInput.model';
import Joi from 'joi';

export const accreditedProgramsSearchUrl = 'https://accreditation.apa.org/accredited-programs';
export const historicalVerificationUrl = 'https://accreditation.apa.org/contact';

@Component({
    name: 'Education',
    components: {
        ApplicationSectionLayout,
        ApplicationQuestionRow,
        InputText,
        InputSelect,
        InputDate,
        InputPhone,
        InputCheckbox,
        InfoCircleIcon,
    },
})
class Education extends mixins(MixinApplicationSection) {
    //
    // Data
    //
    sectionKey = ApplicationSection.EDUCATION;
    verificationInputs: Record<string, FormInput> = {};
    accreditedProgramsSearchUrl = accreditedProgramsSearchUrl;
    historicalVerificationUrl = historicalVerificationUrl;

    //
    // Computed
    //
    get degreeTypeOptions(): Array<SelectOption> {
        const degreeTypes: Array<{ key?: string, name?: string }> = this.$tm('application.degreeTypeOptions') || [];

        return [
            { value: '', name: `- ${this.$t('common.select')} -` },
            ...degreeTypes.map(({ key = '', name = '' }) => ({ value: key, name })),
        ];
    }

    get accreditingContact(): ApplicationAccreditingContact {
        return this.sectionData.accreditingContact || {};
    }

    get isVerificationRequired(): boolean {
        return this.formData.isAccreditedByAuthority?.value === false;
    }

    get contactAttestationKeys(): Array<string> {
        return (this.accreditingContact.attestations || [])
            .map((attestation) => this.getAttestationKey(attestation, 'contact'));
    }

    get contactAttestationInputs(): Array<FormInput> {
        return this.contactAttestationKeys
            .map((key) => this.formData[key])
            .filter((formInput) => Boolean(formInput));
    }

    //
    // Methods
    //
    initFormInputs(): void {
        const { sectionData } = this;

        this.formData = reactive({
            nameAtTime: new FormInput({
                id: 'name-at-time',
                name: 'name-at-time',
                label: computed(() => this.$t('application.nameAtTimeLabel')),
                placeholder: computed(() => this.$t('application.nameAtTimePlaceholder')),
                value: sectionData.nameAtTime || '',
                validation: this.textValidation(),
            }),
            institution: new FormInput({
                id: 'institution',
                name: 'institution',
                label: computed(() => this.$t('application.institutionLabel')),
                value: sectionData.institution || '',
                validation: this.textValidation(),
            }),
            city: new FormInput({
                id: 'institution-city',
                name: 'institution-city',
                label: computed(() => this.$t('application.cityLabel')),
                value: sectionData.city || '',
                validation: this.textValidation(),
            }),
            state: new FormInput({
                id: 'institution-state',
                name: 'institution-state',
                label: computed(() => this.$t('application.stateOrProvinceLabel')),
                value: sectionData.state || '',
                validation: this.textValidation(),
            }),
            degreeType: new FormInput({
                id: 'degree-type',
                name: 'degree-type',
                label: computed(() => this.$t('application.degreeLabel')),
                value: sectionData.degreeType || '',
                valueOptions: this.degreeTypeOptions,
                validation: Joi.string().required().messages(this.joiMessages.string),
            }),
            program: new FormInput({
                id: 'program',
                name: 'program',
                label: computed(() => this.$t('application.programLabel')),
                value: sectionData.program || '',
                validation: this.textValidation(),
            }),
            department: new FormInput({
                id: 'department',
                name: 'department',
                label: computed(() => this.$t('application.departmentLabel')),
                value: sectionData.department || '',
                validation: this.textValidation(),
            }),
            conferredDate: new FormInput({
                id: 'conferred-date',
                name: 'conferred-date',
                label: computed(() => this.$t('application.conferredDateLabel')),
                placeholder: 'MM/DD/YYYY',
                value: sectionData.conferredDate || '',
                validation: this.dateValidation(),
            }),
            isCompleted: this.createYesNoInput({
                name: 'is-completed',
                label: computed(() => this.$t('application.isCompletedLabel')),
                value: sectionData.isCompleted,
            }),
            accreditingBody: new FormInput({
                id: 'accrediting-body',
                name: 'accrediting-body',
                label: computed(() => this.$t('application.accreditingBodyLabel')),
                value: sectionData.accreditingBody || '',
                validation: this.textValidation(),
            }),
            accreditingYear: new FormInput({
                id: 'accrediting-year',
                name: 'accrediting-year',
                label: computed(() => this.$t('application.accreditingYearLabel')),
                placeholder: computed(() => this.$t('application.accreditingYearPlaceholder')),
                autocomplete: 'off',
                value: sectionData.accreditingYear || '',
                validation: Joi.string().required().max(4).pattern(/^\d{4}$/)
                    .messages({
                        ...this.joiMessages.string,
                        'string.pattern.base': this.$t('application.yearFormat'),
                    }),
                enforceMax: true,
            }),
            isAccreditedByAuthority: this.createYesNoInput({
                name: 'is-accredited-by-authority',
                label: computed(() => this.$t('application.isAccreditedByAuthorityLabel')),
                value: sectionData.isAccreditedByAuthority,
            }),
            isProgramEquivalent: this.createYesNoInput({
                name: 'is-program-equivalent',
                label: computed(() => this.$t('application.isProgramEquivalentLabel')),
                value: sectionData.isProgramEquivalent,
                isRequired: false,
            }),
            hasResidence: this.createYesNoInput({
                name: 'has-residence',
                label: computed(() => this.$t('application.hasResidenceLabel')),
                value: sectionData.hasResidence,
            }),
            submit: new FormInput({
                isSubmitInput: true,
                id: 'submit-education',
            }),
        });
        this.initVerificationInputs();
        this.watchFormInputs();
    }

    initVerificationInputs(): void {
        const { accreditingContact: contact } = this;
        const verificationInputs: Record<string, FormInput> = {
            contactName: new FormInput({
                id: 'contact-name',
                name: 'contact-name',
                label: computed(() => this.$t('application.contactNameLabel')),
                autocomplete: 'off',
                value: contact.name || '',
                validation: this.textValidation(),
            }),
            contactEmail: new FormInput({
                id: 'contact-email',
                name: 'contact-email',
                label: computed(() => this.$t('application.emailLabel')),
                autocomplete: 'off',
                value: contact.email || '',
                validation: Joi.string().required().email({ tlds: false }).max(100)
                    .messages(this.joiMessages.string),
            }),
            contactCity: new FormInput({
                id: 'contact-city',
                name: 'contact-city',
                label: computed(() => this.$t('application.cityLabel')),
                autocomplete: 'off',
                value: contact.city || '',
                validation: this.textValidation(),
            }),
            contactState: new FormInput({
                id: 'contact-state',
                name: 'contact-state',
                label: computed(() => this.$t('application.stateLabel')),
                value: contact.state || '',
                valueOptions: this.stateOptions,
                validation: Joi.string().required().messages(this.joiMessages.string),
            }),
            contactZip: new FormInput({
                id: 'contact-zip',
                name: 'contact-zip',
                label: computed(() => this.$t('application.zipLabel')),
                autocomplete: 'off',
                value: contact.zip || '',
                validation: Joi.string().required().max(10).pattern(/^\d{5}(-\d{4})?$/)
                    .messages({
                        ...this.joiMessages.string,
                        'string.pattern.base': this.$t('application.zipFormat'),
                    }),
                enforceMax: true,
            }),
            contactPhone: new FormInput({
                id: 'contact-phone',
                name: 'contact-phone',
                label: computed(() => this.$t('application.phoneLabel')),
                autocomplete: 'off',
                value: contact.phone || '',
                validation: this.phoneValidation(),
            }),
        };

        (contact.attestations || []).forEach((attestation) => {
            verificationInputs[this.getAttestationKey(attestation, 'contact')] = this.createAttestationCheckboxInput(
                attestation,
                'contact'
            );
        });

        this.verificationInputs = verificationInputs;
        this.toggleFormInputs(this.verificationInputs, this.isVerificationRequired);
    }

    mockPopulate(): void {
        const { formData, verificationInputs } = this;

        formData.nameAtTime.value = 'Test Applicant';
        formData.institution.value = 'University of Psychology';
        formData.city.value = 'Denver';
        formData.state.value = 'Colorado';
        formData.degreeType.value = 'psyd';
        formData.program.value = 'Clinical Psychology';
        formData.department.value = 'Psychology';
        formData.conferredDate.value = '2012-05-20';
        formData.isCompleted.value = true;
        formData.accreditingBody.value = 'Higher Learning Commission';
        formData.accreditingYear.value = '2010';
        formData.isAccreditedByAuthority.value = true;
        formData.isProgramEquivalent.value = false;
        formData.hasResidence.value = true;
        verificationInputs.contactName.value = 'Dr. Mock Contact';
        verificationInputs.contactEmail.value = 'contact@example.com';
        verificationInputs.contactCity.value = 'Denver';
        verificationInputs.contactState.value = 'co';
        verificationInputs.contactZip.value = '80202';
        verificationInputs.contactPhone.value = '+13035551234';
        this.contactAttestationKeys.forEach((key) => {
            verificationInputs[key].value = true as any;
        });
    }

    clearableFormInputs(): Array<FormInput> {
        const verificationInputs = Object.values(this.verificationInputs);

        return [
            ...this.formInputs.filter((formInput) => !verificationInputs.includes(formInput)),
            ...verificationInputs,
        ];
    }

    async prepSectionRequestData(): Promise<object> {
        const { formValues, sectionData, accreditingContact } = this;
        const isVerificationRequired = formValues.isAccreditedByAuthority === false;
        const transcripts = await this.prepFiles(sectionData.transcripts || []);

        return {
            nameAtTime: formValues.nameAtTime,
            institution: formValues.institution,
            city: formValues.city,
            state: formValues.state,
            degreeType: formValues.degreeType,
            program: formValues.program,
            department: formValues.department,
            conferredDate: formValues.conferredDate,
            isCompleted: formValues.isCompleted,
            accreditingBody: formValues.accreditingBody,
            accreditingYear: formValues.accreditingYear,
            isAccreditedByAuthority: formValues.isAccreditedByAuthority,
            isProgramEquivalent: formValues.isProgramEquivalent ?? null,
            hasResidence: formValues.hasResidence,
            accreditingContact: {
                name: (isVerificationRequired) ? formValues.contactName : null,
                email: (isVerificationRequired) ? formValues.contactEmail : null,
                city: (isVerificationRequired) ? formValues.contactCity : null,
                state: (isVerificationRequired) ? formValues.contactState : null,
                zip: (isVerificationRequired) ? formValues.contactZip : null,
                phone: (isVerificationRequired) ? formValues.contactPhone : null,
                attestations: this.prepAttestations(accreditingContact.attestations, {
                    prefix: 'contact',
                    shouldReset: !isVerificationRequired,
                }),
            },
            transcripts,
        };
    }

    //
    // Watchers
    //
    @Watch('isVerificationRequired') onVerificationRequiredChange(): void {
        this.toggleFormInputs(this.verificationInputs, this.isVerificationRequired);
    }
}

export default toNative(Education);

// export default Education;
