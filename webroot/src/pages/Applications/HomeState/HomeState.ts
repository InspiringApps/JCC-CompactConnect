//
//  HomeState.ts
//  CompactConnect
//
//  Created by InspiringApps on 11/24/2026.
//

import { Component, mixins, toNative } from 'vue-facing-decorator';
import { reactive, computed } from 'vue';
import MixinApplicationSection from '@pages/Applications/_mixins/applicationSection.mixin';
import ApplicationSectionLayout from '@components/ApplicationSectionLayout/ApplicationSectionLayout.vue';
import ApplicationFileList from '@components/ApplicationFileList/ApplicationFileList.vue';
import InputSelect from '@components/Forms/InputSelect/InputSelect.vue';
import InputDate from '@components/Forms/InputDate/InputDate.vue';
import InputCheckbox from '@components/Forms/InputCheckbox/InputCheckbox.vue';
import InputFile from '@components/Forms/InputFile/InputFile.vue';
import {
    ApplicationFile,
    ApplicationHomeState,
    ApplicationSection,
    ApplicationType
} from '@models/Application/Application.model';
import { FormInput } from '@models/FormInput/FormInput.model';
import Joi from 'joi';

export const homeStatePolicyUrl = 'https://psypact.org/page/Rules';

interface HomeStateSection {
    type: ApplicationType;
    typeName: string;
    homeState: ApplicationHomeState;
}

@Component({
    name: 'HomeState',
    components: {
        ApplicationSectionLayout,
        ApplicationFileList,
        InputSelect,
        InputDate,
        InputCheckbox,
        InputFile,
    },
})
class HomeState extends mixins(MixinApplicationSection) {
    //
    // Data
    //
    sectionKey = ApplicationSection.HOME_STATE;
    existingDocuments: Record<string, Array<ApplicationFile>> = {};
    homeStatePolicyUrl = homeStatePolicyUrl;

    //
    // Computed
    //
    get homeStateSections(): Array<HomeStateSection> {
        const types: Array<ApplicationType> = this.applicationData.types || [];
        const homeStates: Array<ApplicationHomeState> = this.sectionData.applicationTypes || [];
        const typeTranslations = this.$tm('application.applicationTypes') || [];

        return homeStates
            .filter((homeState) => homeState.applicationType && types.includes(homeState.applicationType))
            .map((homeState) => {
                const type = homeState.applicationType as ApplicationType;

                return {
                    type,
                    typeName: typeTranslations.find((translate) => translate.key === type)?.abbrev || type,
                    homeState,
                };
            });
    }

    //
    // Methods
    //
    attestationPrefix(type: string): string {
        return `homeState-${type}`;
    }

    formInputFor(type: string, field: string): FormInput {
        return this.formData[`${type}${field}`];
    }

    attestationInputs(section: HomeStateSection): Array<FormInput> {
        const prefix = this.attestationPrefix(section.type);

        return (section.homeState.attestations || [])
            .map((attestation) => this.formData[this.getAttestationKey(attestation, prefix)])
            .filter((formInput) => Boolean(formInput));
    }

    isActiveMilitary(type: string): boolean {
        return (this.formInputFor(type, 'IsActiveMilitary')?.value as unknown) === true;
    }

    initFormInputs(): void {
        const formData: any = {};
        const existingDocuments: Record<string, Array<ApplicationFile>> = {};

        this.homeStateSections.forEach(({ type, typeName, homeState }) => {
            formData[`${type}State`] = new FormInput({
                id: `${type}-home-state`,
                name: `${type}-home-state`,
                label: computed(() => this.$t('application.homeStateLabel', { type: typeName })),
                value: homeState.state || '',
                valueOptions: this.stateOptions,
                validation: Joi.string().required().messages(this.joiMessages.string),
            });
            formData[`${type}StartDate`] = new FormInput({
                id: `${type}-start-date`,
                name: `${type}-start-date`,
                label: computed(() => this.$t('application.startDateLabel')),
                placeholder: 'MM/DD/YYYY',
                value: homeState.startDate || '',
                validation: this.dateValidation(),
            });
            formData[`${type}IsActiveMilitary`] = new FormInput({
                id: `${type}-is-active-military`,
                name: `${type}-is-active-military`,
                label: computed(() => this.$t('application.isActiveMilitaryLabel')),
                value: homeState.isActiveMilitary === true,
            });
            formData[`${type}MilitaryDocuments`] = this.createFileInput(
                `${type}-military-documents`,
                this.$t('application.militaryDocumentsTitle')
            );

            (homeState.attestations || []).forEach((attestation) => {
                const prefix = this.attestationPrefix(type);

                formData[this.getAttestationKey(attestation, prefix)] = this.createAttestationCheckboxInput(
                    attestation,
                    prefix
                );
            });

            existingDocuments[type] = [...(homeState.militaryDocuments || [])];
        });

        formData.submit = new FormInput({
            isSubmitInput: true,
            id: 'submit-home-state',
        });

        this.formData = reactive(formData);
        this.existingDocuments = existingDocuments;
        this.homeStateSections.forEach(({ type }) => this.updateMilitaryDocumentsValidation(type));
        this.watchFormInputs();
    }

    updateMilitaryDocumentsValidation(type: string): void {
        const isRequired = this.isActiveMilitary(type) && !(this.existingDocuments[type] || []).length;
        const validation = (isRequired) ? Joi.array().min(1) : Joi.array();

        this.updateInputValidation(
            this.formInputFor(type, 'MilitaryDocuments'),
            validation.messages(this.joiMessages.files)
        );
    }

    onActiveMilitaryChange(type: string): void {
        this.updateMilitaryDocumentsValidation(type);
    }

    removeExistingDocument(type: string, file: ApplicationFile): void {
        this.existingDocuments = {
            ...this.existingDocuments,
            [type]: (this.existingDocuments[type] || []).filter((document) => document !== file),
        };
        this.updateMilitaryDocumentsValidation(type);
        this.updateFormSubmitSuccess('');
    }

    mockPopulate(): void {
        const mockStates = ['co', 'ne', 'ky'];

        this.homeStateSections.forEach((section, index) => {
            this.formInputFor(section.type, 'State').value = mockStates[index % mockStates.length];
            this.formInputFor(section.type, 'StartDate').value = '2020-01-15';
            this.formInputFor(section.type, 'IsActiveMilitary').value = false as any;
            this.attestationInputs(section).forEach((formInput) => {
                formInput.value = true as any;
            });
            this.updateMilitaryDocumentsValidation(section.type);
        });
    }

    afterClearForm(): void {
        this.homeStateSections.forEach(({ type }) => this.updateMilitaryDocumentsValidation(type));
    }

    async prepSectionRequestData(): Promise<object> {
        const { formValues } = this;
        const homeStates: Array<ApplicationHomeState> = this.sectionData.applicationTypes || [];
        const applicationTypes = await Promise.all(homeStates.map(async (homeState) => {
            const type = homeState.applicationType as string;
            const isShown = this.homeStateSections.some((section) => section.type === type);
            let prepped: object;

            if (isShown) {
                const isActiveMilitary = formValues[`${type}IsActiveMilitary`] === true;

                prepped = {
                    applicationType: type,
                    state: formValues[`${type}State`],
                    startDate: formValues[`${type}StartDate`],
                    isActiveMilitary,
                    militaryDocuments: (isActiveMilitary)
                        ? await this.prepFiles(this.existingDocuments[type], formValues[`${type}MilitaryDocuments`])
                        : [],
                    attestations: this.prepAttestations(homeState.attestations, {
                        prefix: this.attestationPrefix(type),
                    }),
                };
            } else {
                prepped = {
                    applicationType: type,
                    state: homeState.state ?? null,
                    startDate: homeState.startDate ?? null,
                    isActiveMilitary: homeState.isActiveMilitary === true,
                    militaryDocuments: await this.prepFiles(homeState.militaryDocuments),
                    attestations: this.prepAttestations(homeState.attestations),
                };
            }

            return prepped;
        }));

        return { applicationTypes };
    }
}

export default toNative(HomeState);

// export default HomeState;
