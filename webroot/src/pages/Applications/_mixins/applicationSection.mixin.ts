//
//  applicationSection.mixin.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import { Component, mixins, Watch } from 'vue-facing-decorator';
import { computed, nextTick } from 'vue';
import { stateList } from '@/app.config';
import MixinForm from '@components/Forms/_mixins/form.mixin';
import {
    Application,
    ApplicationAttestation,
    ApplicationAttestationsSerializer,
    ApplicationFile,
    ApplicationFilesSerializer,
    ApplicationReview,
    ApplicationSection,
    ApplicantSectionStatus,
    InterfaceApplicationCreate
} from '@models/Application/Application.model';
import { FormInput } from '@models/FormInput/FormInput.model';
import { State } from '@models/State/State.model';
import Joi from 'joi';
import { isValidPhoneNumber } from 'libphonenumber-js';

export interface SelectOption {
    value: string | number | boolean | null;
    name: string;
    isDisabled?: boolean;
}

export const applicationSectionRoutes: Record<ApplicationSection, string> = {
    [ApplicationSection.PERSONAL_INFORMATION]: 'ApplicationPersonalInformation',
    [ApplicationSection.LICENSE_HISTORY]: 'ApplicationLicenseHistory',
    [ApplicationSection.EDUCATION]: 'ApplicationEducation',
    [ApplicationSection.CONDUCT_HISTORY]: 'ApplicationConductHistory',
    [ApplicationSection.HOME_STATE]: 'ApplicationHomeState',
    [ApplicationSection.ACKNOWLEDGEMENTS]: 'ApplicationAcknowledgements',
};

export const applicationSectionOrder: Array<ApplicationSection> = [
    ApplicationSection.PERSONAL_INFORMATION,
    ApplicationSection.LICENSE_HISTORY,
    ApplicationSection.EDUCATION,
    ApplicationSection.CONDUCT_HISTORY,
    ApplicationSection.HOME_STATE,
    ApplicationSection.ACKNOWLEDGEMENTS,
];

export const applicationTextMaxLength = 80;
export const applicationDocumentTypes = ['application/pdf', 'image/png', 'image/jpeg'];
export const applicationDocumentMaxSizeMb = 9;

@Component({
    name: 'MixinApplicationSection',
})
class MixinApplicationSection extends mixins(MixinForm) {
    //
    // Data
    //
    sectionKey: ApplicationSection = ApplicationSection.PERSONAL_INFORMATION;
    hasFetched = false;
    fetchedApplication: Application | null = null;
    isFormReady = false;
    isPageActive = true;
    formRenderKey = 0;
    watchedFormKeys: Array<string> = [];

    //
    // Lifecycle
    //
    async created() {
        await this.fetchApplication();
    }

    beforeUnmount() {
        this.isPageActive = false;
    }

    //
    // Computed
    //
    get userStore(): any {
        return this.$store.state.user;
    }

    get compactType(): string {
        return this.userStore.currentCompact?.type || String(this.$route.params.compact || '');
    }

    get applicationId(): string {
        return String(this.$route.params.applicationId || '');
    }

    get storeApplication(): Application | null {
        const applications: Array<Application> = this.userStore.model?.licensee?.applications || [];

        return applications.find((application) => String(application.id) === this.applicationId) || null;
    }

    get application(): Application | null {
        return this.storeApplication || this.fetchedApplication;
    }

    get applicationData(): InterfaceApplicationCreate {
        return (this.application || {}) as InterfaceApplicationCreate;
    }

    get sectionData(): any {
        return (this.applicationData as any)[this.sectionKey] || {};
    }

    get isLoadError(): boolean {
        return this.hasFetched && !this.application;
    }

    get isEditable(): boolean {
        return this.application?.isEditableByApplicant() || false;
    }

    get sectionTitle(): string {
        const sectionConfigs = this.$tm('application.applicationSections') || [];
        const sectionConfig = sectionConfigs.find((config) => config.key === this.sectionKey);

        return sectionConfig?.name || '';
    }

    get isNeedsAttention(): boolean {
        return this.sectionData.applicantStatus === ApplicantSectionStatus.NEEDS_ATTENTION;
    }

    get attentionNotes(): Array<string> {
        const reviews: Array<ApplicationReview> = this.sectionData.reviews || [];

        return reviews
            .map((review) => review.notesForApplicant || '')
            .filter((note) => Boolean(note));
    }

    get nextRoute(): object {
        const sectionIndex = applicationSectionOrder.indexOf(this.sectionKey);
        const nextSection = applicationSectionOrder[sectionIndex + 1];
        const params = { compact: this.compactType, applicationId: this.applicationId };

        return (nextSection)
            ? { name: applicationSectionRoutes[nextSection], params }
            : { name: 'ApplicationChecklist', params };
    }

    get isMockPopulateEnabled(): boolean {
        return Boolean(this.$envConfig?.isDevelopment);
    }

    get saveLabel(): string {
        return (this.isFormLoading) ? this.$t('common.saving') : this.$t('common.save');
    }

    get isSaveEnabled(): boolean {
        return this.isEditable && !this.isFormLoading;
    }

    get yesNoOptions(): Array<SelectOption> {
        return [
            { value: true, name: this.$t('common.yes') },
            { value: false, name: this.$t('common.no') },
        ];
    }

    get stateOptions(): Array<SelectOption> {
        return this.getStateOptions(this.$t('application.selectState'));
    }

    get attestationMessages(): any {
        const required = this.$t('inputErrors.required');

        return {
            'any.required': required,
            'boolean.base': required,
            'any.only': this.$t('application.mustAnswerYes'),
        };
    }

    get applicationFileConfig(): any {
        return {
            accepts: applicationDocumentTypes,
            allowMultiple: true,
            maxSizeMbPer: applicationDocumentMaxSizeMb,
            maxSizeMbAll: applicationDocumentMaxSizeMb * 5,
            hint: computed(() => this.$t('application.fileTypesHint')),
        };
    }

    //
    // Methods
    //
    async fetchApplication(): Promise<void> {
        const { applicationId } = this;
        const application = await this.$store.dispatch('user/getApplicationRequestLicensee', { applicationId });

        if (applicationId === this.applicationId) {
            this.fetchedApplication = application || null;
            this.hasFetched = true;

            if (this.application && this.isPageActive) {
                this.initFormInputs();
                this.isFormReady = true;
            }
        }
    }

    getStateOptions(placeholder: string): Array<SelectOption> {
        const options: Array<SelectOption> = [{ value: '', name: placeholder }];

        stateList.forEach((stateAbbrev) => {
            options.push({
                value: stateAbbrev.toLowerCase(),
                name: new State({ abbrev: stateAbbrev }).name(),
            });
        });

        return options;
    }

    valueOrNull(value: any): any {
        return (value === '' || value === undefined) ? null : value;
    }

    textValidation(config: { isRequired?: boolean, max?: number } = {}): Joi.StringSchema {
        const { isRequired = true, max = applicationTextMaxLength } = config;
        const validation = Joi.string().max(max);

        return ((isRequired) ? validation.required() : validation.allow(''))
            .messages(this.joiMessages.string) as Joi.StringSchema;
    }

    dateValidation(isRequired = true): Joi.StringSchema {
        const validation = Joi.string().pattern(/^\d{2}\/\d{2}\/\d{4}$/);

        return ((isRequired) ? validation.required() : validation.allow(''))
            .messages(this.joiMessages.dateWithFormat('MM/DD/YYYY')) as Joi.StringSchema;
    }

    phoneValidation(isRequired = true): Joi.StringSchema {
        const validation = Joi.string().custom((value, helpers) => (
            (isValidPhoneNumber(value)) ? value : helpers.error('string.phone')
        ));

        return ((isRequired) ? validation.required() : validation.allow(''))
            .messages({
                ...this.joiMessages.string,
                'string.phone': this.$t('inputErrors.phone'),
            }) as Joi.StringSchema;
    }

    numericValidation(length: number, isRequired = true): Joi.StringSchema {
        const validation = Joi.string().pattern(new RegExp(`^\\d{${length}}$`));

        return ((isRequired) ? validation.required() : validation.allow(''))
            .messages({
                ...this.joiMessages.string,
                'string.pattern.base': this.$t('application.numericLengthFormat', { length }),
            }) as Joi.StringSchema;
    }

    getAttestationKey(attestation: ApplicationAttestation, prefix = 'attestation'): string {
        return `${prefix}-${attestation.attestationId}`;
    }

    createYesNoInput(config: {
        name: string,
        label: any,
        value?: boolean | null,
        isRequired?: boolean,
        mustBeTrue?: boolean,
    }): FormInput {
        const {
            name, label, value = null, isRequired = true, mustBeTrue = false
        } = config;
        let validation = (mustBeTrue) ? Joi.boolean().valid(true) : Joi.boolean();

        validation = (isRequired) ? validation.required() : validation.allow(null);

        // The radio group is labelled by an element with an id matching the input name
        return new FormInput({
            id: `${name}-group`,
            name,
            label,
            shouldHideLabel: true,
            value: value ?? null,
            valueOptions: this.yesNoOptions,
            validation: validation.messages(this.attestationMessages),
        });
    }

    createAttestationRadioInput(
        attestation: ApplicationAttestation,
        config: { prefix?: string, mustBeTrue?: boolean } = {}
    ): FormInput {
        const { prefix, mustBeTrue = false } = config;

        return this.createYesNoInput({
            name: this.getAttestationKey(attestation, prefix),
            label: attestation.text || '',
            value: attestation.value,
            mustBeTrue,
        });
    }

    createAttestationCheckboxInput(attestation: ApplicationAttestation, prefix?: string): FormInput {
        const key = this.getAttestationKey(attestation, prefix);

        return new FormInput({
            id: key,
            name: key,
            label: attestation.text || '',
            value: attestation.value === true,
            validation: Joi.boolean().valid(true).required().messages(this.attestationMessages),
        });
    }

    prepAttestations(
        attestations: Array<ApplicationAttestation> = [],
        config: { prefix?: string, shouldReset?: boolean } = {}
    ): Array<any> {
        const { prefix, shouldReset = false } = config;

        return ApplicationAttestationsSerializer.toServer(attestations.map((attestation) => {
            const formInput = this.formData[this.getAttestationKey(attestation, prefix)];
            let { value } = attestation;

            if (shouldReset) {
                value = null;
            } else if (formInput) {
                ({ value } = formInput);
            }

            return { ...attestation, value };
        }));
    }

    createFileInput(id: string, label: string): FormInput {
        return new FormInput({
            id,
            name: id,
            label,
            shouldHideLabel: true,
            value: [],
            fileConfig: this.applicationFileConfig,
        });
    }

    async uploadFiles(files: Array<File> = []): Promise<Array<ApplicationFile>> {
        let uploadedFiles: Array<ApplicationFile> = [];

        if (files.length) {
            uploadedFiles = await this.$store.dispatch('user/uploadApplicationDocumentsRequest', {
                applicationId: this.applicationId,
                files,
            });
        }

        return uploadedFiles;
    }

    async prepFiles(existingFiles: Array<ApplicationFile> = [], newFiles: Array<File> = []): Promise<Array<any>> {
        const uploadedFiles = await this.uploadFiles(newFiles);

        return ApplicationFilesSerializer.toServer([...existingFiles, ...uploadedFiles]);
    }

    toggleFormInputs(formInputs: Record<string, FormInput>, isShown: boolean): void {
        const { formData } = this;
        let isChanged = false;

        Object.keys(formInputs).forEach((key) => {
            if (isShown && !formData[key]) {
                formData[key] = formInputs[key];
                isChanged = true;
            } else if (!isShown && formData[key]) {
                delete formData[key];
                isChanged = true;
            }
        });

        if (isChanged) {
            this.watchFormInputs();
        }
    }

    updateInputValidation(formInput: FormInput, validation: Joi.Schema): void {
        if (formInput) {
            formInput.validation = validation as any;
            formInput.validate();
            this.checkValidForAll();
        }
    }

    prepSectionRequestData(): Promise<object> | object { // Placeholder method for implementing section pages.
        return {};
    }

    mockPopulate(): void { // Placeholder method for implementing section pages.
        // Continue
    }

    clearableFormInputs(): Array<FormInput> { // Section pages override this to include hidden conditional inputs.
        return this.formInputs;
    }

    afterClearForm(): void { // Placeholder method for section pages to clear any non-input state.
        // Continue
    }

    clearFormValues(): void {
        this.clearableFormInputs().filter((formInput) => !formInput.isSubmitInput).forEach((formInput) => {
            const isYesNo = (formInput.valueOptions || []).some((option: any) => typeof option.value === 'boolean');
            let value: any = '';

            if (isYesNo) {
                value = null;
            } else if (typeof formInput.value === 'boolean') {
                value = false;
            } else if (Array.isArray(formInput.value)) {
                value = [];
            }

            formInput.value = value;
            formInput.isTouched = false;
            formInput.errorMessage = '';
        });
        this.afterClearForm();
    }

    async remountFormInputs(): Promise<void> {
        // Some inputs (e.g. file) only read their value on mount, so re-render them after programmatic changes
        this.formRenderKey += 1;
        await nextTick();
        this.validateAll({ skipErrorScroll: true });
    }

    async handleMockPopulate(): Promise<void> {
        this.mockPopulate();
        await this.remountFormInputs();
        this.scrollToElement(this.formData.submit?.id);
    }

    async handleClearForm(): Promise<void> {
        this.clearFormValues();
        await this.remountFormInputs();
    }

    scrollToElement(elementId?: string): void {
        const element = (elementId) ? document.getElementById(elementId) : null;

        if (element && typeof element.scrollIntoView === 'function') {
            element.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }

    watchFormInputs(): void {
        const { formData } = this;

        // Section forms re-init after saves & add / remove dynamic inputs, so only watch each key once
        this.formKeys.forEach((key) => {
            if (!formData[key].isSubmitInput && !this.watchedFormKeys.includes(key)) {
                this.watchedFormKeys.push(key);
                this.$watch(`formData.${key}`, () => {
                    this.checkValidForAll();
                    this.updateFormSubmitSuccess('');

                    if (!this.isFormError) {
                        this.updateFormSubmitError('');
                    }
                }, { deep: true });
            }
        });

        this.validateAll({ skipErrorScroll: true });
    }

    updateFormSubmitSuccess(message: string): void {
        this.formSubmitInputs.forEach((submitInput) => {
            submitInput.successMessage = message;
        });

        // Further edits after a successful save need to be saved before continuing
        if (!message) {
            this.isFormSuccessful = false;
        }
    }

    async handleSubmit(): Promise<void> {
        this.validateAll({ asTouched: true });

        if (this.isFormValid && this.isSaveEnabled) {
            this.startFormLoading();

            try {
                const sectionData = await this.prepSectionRequestData();
                const application = await this.$store.dispatch('user/updateApplicationRequestLicensee', {
                    data: {
                        id: this.applicationId,
                        [this.sectionKey]: sectionData,
                    },
                });

                if (application && this.isPageActive) {
                    this.fetchedApplication = application;
                    this.initFormInputs();
                    this.formRenderKey += 1;
                    await nextTick();
                    this.updateFormSubmitSuccess(this.$t('application.sectionSaved'));
                    this.isFormSuccessful = true;
                }
            } catch (err: any) {
                this.setError(err?.message || this.$t('serverErrors.networkError'));
            }

            this.endFormLoading();
        }
    }

    continueToNextSection(): void {
        this.$router.push(this.nextRoute);
    }

    //
    // Watchers
    //
    @Watch('applicationId') async onApplicationIdChange(): Promise<void> {
        this.fetchedApplication = null;
        this.hasFetched = false;
        this.isFormReady = false;
        this.isFormSuccessful = false;
        await this.fetchApplication();
    }
}

// export default toNative(MixinApplicationSection);

export default MixinApplicationSection;
